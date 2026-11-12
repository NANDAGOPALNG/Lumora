"""Unit tests for the Cloudflare R2 provider (app/storage/r2_storage.py).

All S3 traffic is faked (FakeS3) or stubbed (botocore Stubber): no real
Cloudflare credentials and no network access are needed.
"""

import asyncio
import io
import logging
import re
import uuid

import pytest
from botocore.exceptions import (
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)
from botocore.response import StreamingBody
from botocore.stub import Stubber

import app.storage.r2_storage as r2_module
from app.config.settings import Settings
from app.storage.base import (
    StorageConfigurationError,
    StorageError,
    StorageNotFoundError,
)
from app.storage.r2_storage import R2Storage, key_from_reference, resolve_r2_config
from tests._r2_support import (  # noqa: F401  (fake_r2 is a fixture)
    ACCESS_KEY_ID,
    ACCOUNT_ID,
    BUCKET,
    SECRET_ACCESS_KEY,
    FakeS3,
    client_error,
    fake_r2,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def provider():
    s3 = FakeS3()
    return R2Storage(client=s3, bucket=BUCKET), s3


def new_ref(provider_, file_type="pdf"):
    return provider_.generate_storage_path(uuid.uuid4(), file_type)


# --------------------------------------------------------------------- upload / read / delete


def test_upload_writes_to_the_configured_bucket_under_the_document_key(provider):
    storage, s3 = provider
    document_id = uuid.uuid4()
    ref = storage.generate_storage_path(document_id, "pdf")

    run(storage.save(ref, b"%PDF-bytes"))

    assert s3.keys() == [f"documents/{document_id}.pdf"]
    assert s3.calls == [("put_object", BUCKET, f"documents/{document_id}.pdf")]
    assert s3.objects[(BUCKET, f"documents/{document_id}.pdf")] == b"%PDF-bytes"
    assert s3.content_types[(BUCKET, f"documents/{document_id}.pdf")] == "application/pdf"


@pytest.mark.parametrize(
    "file_type,content_type",
    [
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("txt", "text/plain; charset=utf-8"),
        ("md", "text/markdown; charset=utf-8"),
        ("xyz", "application/octet-stream"),
    ],
)
def test_upload_sets_a_content_type_for_each_file_type(provider, file_type, content_type):
    storage, s3 = provider
    ref = new_ref(storage, file_type)
    run(storage.save(ref, b"x"))
    assert list(s3.content_types.values()) == [content_type]


def test_save_overwrites_an_existing_object(provider):
    storage, s3 = provider
    ref = new_ref(storage, "txt")
    run(storage.save(ref, b"v1"))
    run(storage.save(ref, b"version two"))
    assert run(storage.read(ref)) == b"version two"
    assert len(s3.keys()) == 1


def test_read_returns_the_stored_bytes_and_closes_the_stream(provider):
    storage, s3 = provider
    ref = new_ref(storage)
    run(storage.save(ref, b"hello bytes"))
    assert run(storage.read(ref)) == b"hello bytes"
    assert s3.calls_for("get_object") == [("get_object", BUCKET, ref[len("r2://"):])]


def test_delete_removes_the_object(provider):
    storage, s3 = provider
    ref = new_ref(storage)
    run(storage.save(ref, b"x"))
    run(storage.delete(ref))
    assert s3.keys() == []
    assert run(storage.exists(ref)) is False


def test_exists_reflects_presence(provider):
    storage, _ = provider
    ref = new_ref(storage)
    assert run(storage.exists(ref)) is False
    run(storage.save(ref, b"x"))
    assert run(storage.exists(ref)) is True


# --------------------------------------------------------------------- missing objects


def test_reading_a_missing_object_raises_not_found(provider):
    storage, _ = provider
    with pytest.raises(StorageNotFoundError):
        run(storage.read(new_ref(storage)))


def test_deleting_a_missing_object_is_not_an_error(provider):
    storage, _ = provider
    run(storage.delete(new_ref(storage)))  # S3 delete is idempotent


def test_delete_tolerates_an_explicit_404_from_the_api(provider):
    storage, s3 = provider
    s3.fail["delete_object"] = client_error("NoSuchKey", "DeleteObject", 404)
    run(storage.delete(new_ref(storage)))


def test_missing_bucket_is_a_storage_error_not_a_missing_object(provider):
    storage, s3 = provider
    s3.fail["get_object"] = client_error("NoSuchBucket", "GetObject", 404)
    with pytest.raises(StorageError) as excinfo:
        run(storage.read(new_ref(storage)))
    assert not isinstance(excinfo.value, StorageNotFoundError)
    assert "NoSuchBucket" in str(excinfo.value)


# --------------------------------------------------------------------- failures


@pytest.mark.parametrize(
    "failure,expected",
    [
        (client_error("AccessDenied", "PutObject", 403), "AccessDenied"),
        (client_error("InternalError", "PutObject", 500), "InternalError"),
        (EndpointConnectionError(endpoint_url="https://x.r2.cloudflarestorage.com"), "EndpointConnectionError"),
        (ConnectTimeoutError(endpoint_url="https://x"), "ConnectTimeoutError"),
        (ReadTimeoutError(endpoint_url="https://x"), "ReadTimeoutError"),
        (NoCredentialsError(), "NoCredentialsError"),
    ],
)
def test_upload_failures_become_storage_errors(provider, failure, expected):
    storage, s3 = provider
    s3.fail["put_object"] = failure
    with pytest.raises(StorageError, match=expected):
        run(storage.save(new_ref(storage), b"x"))


def test_download_and_delete_failures_become_storage_errors(provider):
    storage, s3 = provider
    ref = new_ref(storage)
    run(storage.save(ref, b"x"))
    s3.fail["get_object"] = EndpointConnectionError(endpoint_url="https://x")
    s3.fail["delete_object"] = client_error("InternalError", "DeleteObject", 500)
    with pytest.raises(StorageError, match="download failed"):
        run(storage.read(ref))
    with pytest.raises(StorageError, match="delete failed"):
        run(storage.delete(ref))


def test_a_failed_upload_stores_nothing(provider):
    storage, s3 = provider
    s3.fail["put_object"] = client_error("InternalError", "PutObject", 500)
    with pytest.raises(StorageError):
        run(storage.save(new_ref(storage), b"x"))
    assert s3.keys() == []


def test_oversized_object_is_refused_by_declared_length(provider, monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "1")
    storage, s3 = provider
    ref = new_ref(storage)
    run(storage.save(ref, b"small"))
    s3.declared_length = 5 * 1024 * 1024
    with pytest.raises(StorageError, match="maximum document size"):
        run(storage.read(ref))


def test_oversized_object_is_refused_even_if_the_declared_length_lies(provider, monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "1")
    storage, s3 = provider
    ref = new_ref(storage)
    run(storage.save(ref, b"x" * (1024 * 1024 + 10)))
    s3.declared_length = 10  # a wrong length must not defeat the cap
    with pytest.raises(StorageError, match="maximum document size"):
        run(storage.read(ref))


def test_object_exactly_at_the_limit_is_readable(provider, monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "1")
    storage, _ = provider
    ref = new_ref(storage)
    run(storage.save(ref, b"x" * (1024 * 1024)))
    assert len(run(storage.read(ref))) == 1024 * 1024


def test_blocking_s3_calls_do_not_block_the_event_loop(provider):
    storage, s3 = provider
    s3.delay = 0.4  # time.sleep inside the (synchronous) fake client

    async def scenario():
        ticks = 0
        done = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not done.is_set():
                await asyncio.sleep(0.02)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            await storage.save(new_ref(storage), b"x")
        finally:
            done.set()
            await task
        return ticks

    assert run(scenario()) >= 10


# --------------------------------------------------------------------- keys / references


def test_generated_references_are_uuid_based_and_ignore_filenames(provider):
    storage, _ = provider
    document_id = uuid.uuid4()
    ref = storage.generate_storage_path(document_id, "pdf")
    assert ref == f"r2://documents/{document_id}.pdf"
    assert re.fullmatch(r"r2://documents/[0-9a-f-]{36}\.pdf", ref)


@pytest.mark.parametrize("hostile", ["../../etc/passwd", "pdf/../x", "a/b", "p\\df", "PDF"])
def test_file_type_cannot_inject_path_components(provider, hostile):
    storage, _ = provider
    ref = storage.generate_storage_path(uuid.uuid4(), hostile)
    key = ref[len("r2://"):]
    assert key.count("/") == 1 and ".." not in key and "\\" not in key
    assert key_from_reference(ref) == key


def test_every_generated_reference_is_unique(provider):
    storage, _ = provider
    refs = {storage.generate_storage_path(uuid.uuid4(), "txt") for _ in range(50)}
    assert len(refs) == 50


@pytest.mark.parametrize(
    "bad",
    [
        "r2://",
        "r2:///absolute/key",
        "r2://documents/../../other",
        "r2://documents\\evil",
        "r2://documents/\x00x",
        "/var/storage/documents/abc.pdf",  # a legacy local path is not an R2 reference
        "C:\\storage\\abc.pdf",
        "documents/abc.pdf",
        "r2://" + "a" * 2000,
        None,
    ],
)
def test_invalid_references_are_rejected_without_calling_s3(provider, bad):
    storage, s3 = provider
    with pytest.raises(StorageError):
        run(storage.read(bad))
    with pytest.raises(StorageError):
        run(storage.save(bad, b"x"))
    with pytest.raises(StorageError):
        run(storage.delete(bad))
    assert s3.calls == []


# --------------------------------------------------------------------- real boto3 client + Stubber


def test_real_boto3_client_is_configured_for_r2():
    client = r2_module.create_s3_client(
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=SECRET_ACCESS_KEY,
    )
    config = client.meta.config
    assert client.meta.endpoint_url == f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"
    assert client.meta.region_name == "auto"
    assert config.signature_version == "s3v4"
    assert config.connect_timeout == 5 and config.read_timeout == 30
    assert config.retries["total_max_attempts"] == 3  # 3 tries in all, not 3 retries
    assert config.s3["addressing_style"] == "path"
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"


def test_stubbed_boto3_client_validates_bucket_and_key_parameters():
    """botocore's Stubber checks the exact request parameters and validates
    them against the real S3 API model, with no network traffic."""
    client = r2_module.create_s3_client(
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=SECRET_ACCESS_KEY,
    )
    storage = R2Storage(client=client, bucket=BUCKET)
    document_id = uuid.uuid4()
    ref = storage.generate_storage_path(document_id, "pdf")
    key = f"documents/{document_id}.pdf"
    payload = b"%PDF-1.4 stub"

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            expected_params={"Bucket": BUCKET, "Key": key, "Body": payload, "ContentType": "application/pdf"},
        )
        stubber.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(payload), len(payload)), "ContentLength": len(payload)},
            expected_params={"Bucket": BUCKET, "Key": key},
        )
        stubber.add_response("head_object", {}, expected_params={"Bucket": BUCKET, "Key": key})
        stubber.add_response("delete_object", {}, expected_params={"Bucket": BUCKET, "Key": key})

        run(storage.save(ref, payload))
        assert run(storage.read(ref)) == payload
        assert run(storage.exists(ref)) is True
        run(storage.delete(ref))
        stubber.assert_no_pending_responses()


def test_stubbed_service_errors_map_to_not_found_and_storage_error():
    client = r2_module.create_s3_client(
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=SECRET_ACCESS_KEY,
    )
    storage = R2Storage(client=client, bucket=BUCKET)
    ref = storage.generate_storage_path(uuid.uuid4(), "txt")
    with Stubber(client) as stubber:
        stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
        stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
        with pytest.raises(StorageNotFoundError):
            run(storage.read(ref))
        with pytest.raises(StorageError, match="AccessDenied"):
            run(storage.save(ref, b"x"))


# --------------------------------------------------------------------- configuration


def settings_from(monkeypatch, **overrides):
    names = {
        "r2_account_id": "R2_ACCOUNT_ID",
        "r2_access_key_id": "R2_ACCESS_KEY_ID",
        "r2_secret_access_key": "R2_SECRET_ACCESS_KEY",
        "r2_bucket_name": "R2_BUCKET_NAME",
        "r2_endpoint_url": "R2_ENDPOINT_URL",
    }
    base = {
        "r2_account_id": ACCOUNT_ID,
        "r2_access_key_id": ACCESS_KEY_ID,
        "r2_secret_access_key": SECRET_ACCESS_KEY,
        "r2_bucket_name": BUCKET,
        "r2_endpoint_url": None,
    }
    base.update(overrides)
    for field, env_name in names.items():
        if base[field] is None:
            monkeypatch.delenv(env_name, raising=False)
        else:
            monkeypatch.setenv(env_name, base[field])
    return Settings.get_instance()


def test_valid_configuration_derives_the_endpoint_from_the_account_id(monkeypatch):
    config = resolve_r2_config(settings_from(monkeypatch))
    assert config["endpoint_url"] == f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"
    assert config["bucket"] == BUCKET


def test_explicit_endpoint_overrides_the_account_id(monkeypatch):
    config = resolve_r2_config(
        settings_from(monkeypatch, r2_account_id=None, r2_endpoint_url="https://custom.example.com/")
    )
    assert config["endpoint_url"] == "https://custom.example.com"  # trailing slash trimmed


@pytest.mark.parametrize(
    "overrides,missing",
    [
        ({"r2_access_key_id": None}, "R2_ACCESS_KEY_ID"),
        ({"r2_secret_access_key": None}, "R2_SECRET_ACCESS_KEY"),
        ({"r2_bucket_name": None}, "R2_BUCKET_NAME"),
        ({"r2_account_id": None}, "R2_ACCOUNT_ID"),
        ({"r2_access_key_id": "   "}, "R2_ACCESS_KEY_ID"),  # blank counts as missing
        ({"r2_bucket_name": ""}, "R2_BUCKET_NAME"),
    ],
)
def test_missing_settings_are_named_but_never_their_values(monkeypatch, overrides, missing):
    with pytest.raises(StorageConfigurationError) as excinfo:
        resolve_r2_config(settings_from(monkeypatch, **overrides))
    message = str(excinfo.value)
    assert missing in message
    assert SECRET_ACCESS_KEY not in message and ACCESS_KEY_ID not in message


def test_everything_missing_lists_every_variable(monkeypatch):
    settings = settings_from(
        monkeypatch,
        r2_account_id=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_bucket_name=None,
    )
    with pytest.raises(StorageConfigurationError) as excinfo:
        resolve_r2_config(settings)
    for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "R2_ACCOUNT_ID"):
        assert name in str(excinfo.value)


@pytest.mark.parametrize("bucket", ["ab", "UPPER-case", "has_underscore", "-leading", "trailing-", "a" * 64, "has space"])
def test_invalid_bucket_names_are_rejected(monkeypatch, bucket):
    with pytest.raises(StorageConfigurationError, match="R2_BUCKET_NAME is invalid"):
        resolve_r2_config(settings_from(monkeypatch, r2_bucket_name=bucket))


@pytest.mark.parametrize("account_id", ["bad/id", "evil.com#", "a b", "id@host"])
def test_invalid_account_ids_are_rejected(monkeypatch, account_id):
    with pytest.raises(StorageConfigurationError, match="R2_ACCOUNT_ID is invalid"):
        resolve_r2_config(settings_from(monkeypatch, r2_account_id=account_id))


def test_plain_http_endpoints_are_rejected_except_for_localhost(monkeypatch):
    with pytest.raises(StorageConfigurationError, match="https://"):
        resolve_r2_config(settings_from(monkeypatch, r2_endpoint_url="http://r2.example.com"))
    config = resolve_r2_config(settings_from(monkeypatch, r2_endpoint_url="http://localhost:9000"))
    assert config["endpoint_url"] == "http://localhost:9000"


def test_from_settings_passes_credentials_only_to_the_client_factory(monkeypatch, fake_r2):
    storage = R2Storage.from_settings(Settings.get_instance())
    assert fake_r2.client_factory_calls == [
        {
            "endpoint_url": f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            "access_key_id": ACCESS_KEY_ID,
            "secret_access_key": SECRET_ACCESS_KEY,
        }
    ]
    assert SECRET_ACCESS_KEY not in repr(storage) and ACCESS_KEY_ID not in repr(storage)


# --------------------------------------------------------------------- no credentials in logs/errors


def test_credentials_never_appear_in_errors_logs_or_reprs(monkeypatch, caplog, fake_r2):
    from app.storage.factory import delete_stored_file, get_storage_for_new_documents

    s3 = fake_r2.s3
    secrets = [SECRET_ACCESS_KEY, ACCESS_KEY_ID]
    storage = get_storage_for_new_documents()
    ref = storage.generate_storage_path(uuid.uuid4(), "pdf")

    failures = [
        client_error("AccessDenied", "PutObject", 403),
        client_error("InternalError", "PutObject", 500),
        EndpointConnectionError(endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com"),
        ReadTimeoutError(endpoint_url="https://x"),
    ]
    texts = []
    with caplog.at_level(logging.DEBUG):
        for failure in failures:
            s3.fail["put_object"] = failure
            s3.fail["delete_object"] = failure
            with pytest.raises(StorageError) as excinfo:
                run(storage.save(ref, b"x"))
            texts += [str(excinfo.value), repr(excinfo.value), str(excinfo.value.__cause__)]
            assert run(delete_stored_file(ref)) is False  # logs the failure
        # configuration errors too
        monkeypatch.delenv("R2_BUCKET_NAME")
        with pytest.raises(StorageConfigurationError) as excinfo:
            resolve_r2_config(Settings.get_instance())
        texts.append(str(excinfo.value))
    texts += [caplog.text, repr(storage), str(storage)]

    for text in texts:
        for secret in secrets:
            assert secret not in text
