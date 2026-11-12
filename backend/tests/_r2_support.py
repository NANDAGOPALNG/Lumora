"""Shared fakes for the Cloudflare R2 storage tests.

`FakeS3` is an in-memory stand-in for the boto3 S3 client. No test using it
needs Cloudflare credentials or a network connection.
"""

import io
import time

import pytest
from botocore.exceptions import ClientError

import app.storage.r2_storage as r2_module
from app.storage import factory

ACCOUNT_ID = "0123456789abcdef0123456789abcdef"
ACCESS_KEY_ID = "AKIAFAKEACCESSKEYID1234"
SECRET_ACCESS_KEY = "fakeSecretAccessKey/ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
BUCKET = "lumora-test-docs"


def client_error(code: str, operation: str, status: int = 400) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "boom"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        operation,
    )


class _Body:
    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)
        self.closed = False

    def read(self, amt=None):
        return self._stream.read(amt)

    def close(self):
        self.closed = True


class FakeS3:
    """In-memory S3 client with call recording and failure injection."""

    def __init__(self):
        self.objects = {}  # (bucket, key) -> bytes
        self.content_types = {}
        self.calls = []  # (operation, bucket, key)
        self.fail = {}  # operation -> exception (or callable returning one)
        self.delay = 0.0  # seconds each call blocks (to prove the loop isn't blocked)
        self.declared_length = None  # override ContentLength on get_object

    # -- helpers ----------------------------------------------------------
    def _enter(self, operation, Bucket, Key):
        self.calls.append((operation, Bucket, Key))
        if self.delay:
            time.sleep(self.delay)
        failure = self.fail.get(operation)
        if failure is not None:
            raise failure() if callable(failure) else failure

    def calls_for(self, operation):
        return [call for call in self.calls if call[0] == operation]

    def keys(self, bucket=BUCKET):
        return sorted(key for (b, key) in self.objects if b == bucket)

    # -- boto3 S3 client surface used by R2Storage ------------------------
    def put_object(self, *, Bucket, Key, Body, ContentType=None, **kwargs):
        self._enter("put_object", Bucket, Key)
        self.objects[(Bucket, Key)] = bytes(Body)
        self.content_types[(Bucket, Key)] = ContentType
        return {}

    def get_object(self, *, Bucket, Key):
        self._enter("get_object", Bucket, Key)
        if (Bucket, Key) not in self.objects:
            raise client_error("NoSuchKey", "GetObject", 404)
        data = self.objects[(Bucket, Key)]
        length = self.declared_length if self.declared_length is not None else len(data)
        return {"Body": _Body(data), "ContentLength": length}

    def delete_object(self, *, Bucket, Key):
        self._enter("delete_object", Bucket, Key)
        self.objects.pop((Bucket, Key), None)
        return {}

    def head_object(self, *, Bucket, Key):
        self._enter("head_object", Bucket, Key)
        if (Bucket, Key) not in self.objects:
            raise client_error("404", "HeadObject", 404)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}


class R2Env:
    """Handle returned by the `fake_r2` fixture."""

    def __init__(self, monkeypatch, s3: FakeS3):
        self._monkeypatch = monkeypatch
        self.s3 = s3
        self.client_factory_calls = []

    def use_backend(self, name: str) -> None:
        self._monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", name)
        factory.reset_cache()


@pytest.fixture
def fake_r2(monkeypatch):
    """Select the R2 backend with complete (fake) settings and a FakeS3 client."""
    s3 = FakeS3()
    env = R2Env(monkeypatch, s3)

    def fake_create_s3_client(**kwargs):
        env.client_factory_calls.append(kwargs)
        return s3

    monkeypatch.setattr(r2_module, "create_s3_client", fake_create_s3_client)
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setenv("R2_ACCESS_KEY_ID", ACCESS_KEY_ID)
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", SECRET_ACCESS_KEY)
    monkeypatch.setenv("R2_BUCKET_NAME", BUCKET)
    monkeypatch.delenv("R2_ENDPOINT_URL", raising=False)
    factory.reset_cache()
    yield env
    factory.reset_cache()
