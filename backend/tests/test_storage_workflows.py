"""Stage 3 tests: storage provider selection, legacy-document routing, and
every service workflow that touches stored files (upload, reindex, delete,
workspace delete, GitHub sync, Google Drive sync) with local and R2 storage.

R2 is an in-memory fake S3 client (tests/_r2_support.py): no test needs
Cloudflare credentials or network access.
"""

import asyncio
import logging
import os
import uuid
from io import BytesIO

import pytest
from docx import Document as DocxDocument
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.connector  # noqa: F401 - registers ORM models on Base
import app.models.document  # noqa: F401
import app.models.user  # noqa: F401
import app.models.workspace  # noqa: F401
import main
from app.connectors.github_connector import GitHubFile
from app.connectors.google_drive_connector import GoogleDriveFetchedFile
from app.database.base import Base
from app.ingestion import extract_chunks, extract_chunks_from_bytes
from app.ingestion import parsers
from app.models.chunk import Chunk
from app.models.connector import Connector
from app.models.document import DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services import document_service as document_service_module
from app.services.connector_service import ConnectorService
from app.services.document_service import DocumentService, IngestionFailedError
from app.services.workspace_service import WorkspaceService
from app.storage import factory, local_storage
from app.storage.base import (
    StorageConfigurationError,
    StorageError,
    StorageNotFoundError,
)
from app.storage.factory import (
    delete_stored_file,
    get_storage_for_new_documents,
    get_storage_for_path,
    validate_storage_configuration,
)
from app.storage.local_storage import LocalStorage
from app.storage.r2_storage import R2Storage
from tests._r2_support import (  # noqa: F401  (fake_r2 is a fixture)
    ACCESS_KEY_ID,
    BUCKET,
    SECRET_ACCESS_KEY,
    client_error,
    fake_r2,
)

TEXT = ("Lumora stores documents safely. " * 40).encode()  # long enough to chunk
NEW_TEXT = ("A completely different revised body of text. " * 40).encode()


# --------------------------------------------------------------------------- fixtures / helpers


async def _fake_embed_texts(texts, task="retrieval.passage", batch_size=None):
    return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def __init__(self):
        self.upserted = []
        self.deleted_document_ids = []

    async def upsert_chunks(self, chunks):
        self.upserted.extend(chunks)

    async def delete_document_chunks(self, document_id):
        self.deleted_document_ids.append(document_id)


@pytest.fixture
def local_dir(monkeypatch, tmp_path):
    """Local storage root for the test; also fakes embeddings."""
    root = tmp_path / "local-docs"
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(root))
    monkeypatch.setattr(document_service_module, "embed_texts", _fake_embed_texts)
    factory.reset_cache()
    yield root
    factory.reset_cache()


def local_files(root):
    return sorted(os.listdir(root)) if os.path.exists(root) else []


class World:
    """An in-memory database with one user, one workspace and one connector."""

    def __init__(self, engine, session_factory, user, workspace, connector):
        self.engine = engine
        self.session_factory = session_factory
        self.user = user
        self.workspace = workspace
        self.connector = connector
        self.vector_store = FakeVectorStore()

    def document_service(self, session):
        return DocumentService(
            DocumentRepository(session),
            WorkspaceRepository(session),
            ChunkRepository(session),
            self.vector_store,
        )

    def connector_service(self, session):
        return ConnectorService(
            ConnectorRepository(session),
            WorkspaceRepository(session),
            self.document_service(session),
        )

    def workspace_service(self, session):
        return WorkspaceService(
            WorkspaceRepository(session), DocumentRepository(session), self.vector_store
        )


async def make_world() -> World:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        user = User(id=uuid.uuid4(), email="a@example.com", name="A")
        workspace = Workspace(id=uuid.uuid4(), user_id=user.id, name="WS")
        connector = Connector(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            type="github",
            connection_name="octocat/Hello-World",
            github_repo="octocat/Hello-World",
            active=True,
        )
        session.add_all([user, workspace, connector])
        await session.commit()
    return World(engine, session_factory, user, workspace, connector)


def scenario(coro_fn):
    """Run `coro_fn(world)` against a fresh world."""

    async def runner():
        world = await make_world()
        try:
            return await coro_fn(world)
        finally:
            await world.engine.dispose()

    return asyncio.run(runner())


async def upload(world, session, filename="notes.txt", content=TEXT, **kwargs):
    return await world.document_service(session).upload_document(
        workspace_id=world.workspace.id,
        user_id=world.user.id,
        filename=filename,
        content_type=None,
        content=content,
        **kwargs,
    )


async def get_document(world, session, document_id):
    return await DocumentRepository(session).get_by_id_and_workspace_owner(
        document_id, world.user.id
    )


def r2_keys(fake_r2):
    return fake_r2.s3.keys()


def make_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 20 100 Td ({text}) Tj ET".encode("latin-1")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"5 0 obj\n<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream\nendobj\n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF"
    )


def make_docx(*paragraphs: str) -> bytes:
    buf = BytesIO()
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buf)
    return buf.getvalue()


# =========================================================================== provider selection


def test_default_backend_is_local(local_dir, monkeypatch):
    monkeypatch.delenv("DOCUMENT_STORAGE_BACKEND", raising=False)
    assert get_storage_for_new_documents().name == "local"
    assert isinstance(get_storage_for_new_documents(), LocalStorage)


def test_r2_backend_is_selected_for_new_documents(fake_r2):
    storage = get_storage_for_new_documents()
    assert isinstance(storage, R2Storage) and storage.name == "r2"
    assert get_storage_for_new_documents() is storage  # one cached client
    assert len(fake_r2.client_factory_calls) == 1


def test_backend_name_is_case_and_whitespace_insensitive(fake_r2):
    fake_r2.use_backend(" R2 ")
    assert get_storage_for_new_documents().name == "r2"


def test_unknown_backend_is_a_configuration_error(local_dir, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "s3")
    with pytest.raises(StorageConfigurationError, match="DOCUMENT_STORAGE_BACKEND"):
        get_storage_for_new_documents()


def test_existing_documents_are_routed_by_their_reference_not_the_current_backend(fake_r2, local_dir):
    legacy = str(local_dir / f"{uuid.uuid4()}.pdf")
    r2_ref = "r2://documents/abc.pdf"

    for backend in ("r2", "local"):
        fake_r2.use_backend(backend)
        assert get_storage_for_path(legacy).name == "local"
        assert get_storage_for_path(r2_ref).name == "r2"


def test_r2_reference_without_r2_configuration_fails_clearly(local_dir, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "local")
    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(StorageConfigurationError, match="R2_BUCKET_NAME"):
        get_storage_for_path("r2://documents/abc.pdf")


def test_validate_configuration_is_a_noop_for_local(local_dir):
    validate_storage_configuration()  # must not raise


def test_validate_configuration_names_missing_r2_variables_without_network(fake_r2, monkeypatch):
    monkeypatch.delenv("R2_BUCKET_NAME")
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY")
    with pytest.raises(StorageConfigurationError) as excinfo:
        validate_storage_configuration()
    assert "R2_BUCKET_NAME" in str(excinfo.value) and "R2_SECRET_ACCESS_KEY" in str(excinfo.value)
    assert SECRET_ACCESS_KEY not in str(excinfo.value)
    assert fake_r2.client_factory_calls == [] and fake_r2.s3.calls == []


def test_app_startup_fails_fast_when_r2_is_selected_but_incomplete(fake_r2, monkeypatch):
    monkeypatch.delenv("R2_ACCESS_KEY_ID")

    async def start():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(StorageConfigurationError, match="R2_ACCESS_KEY_ID"):
        asyncio.run(start())


def test_app_startup_with_complete_r2_configuration_makes_no_storage_calls(fake_r2, local_dir):
    async def start():
        async with main.lifespan(main.app):
            pass

    asyncio.run(start())
    assert fake_r2.s3.calls == [] and fake_r2.client_factory_calls == []
    assert not os.path.exists(local_dir)  # initialization created/deleted nothing locally


def test_settings_do_not_repr_r2_credentials(fake_r2):
    from app.config.settings import Settings

    text = repr(Settings.get_instance())
    assert SECRET_ACCESS_KEY not in text and ACCESS_KEY_ID not in text


# =========================================================================== local storage compatibility


def test_local_storage_round_trip(local_dir):
    storage = LocalStorage()
    path = storage.generate_storage_path(uuid.uuid4(), "txt")
    assert os.path.dirname(path) == str(local_dir.resolve())

    async def go():
        assert await storage.exists(path) is False
        await storage.save(path, b"hello")
        assert await storage.exists(path) is True
        assert await storage.read(path) == b"hello"
        await storage.save(path, b"replaced")
        assert await storage.read(path) == b"replaced"
        await storage.delete(path)
        await storage.delete(path)  # already gone: not an error
        assert await storage.exists(path) is False
        with pytest.raises(StorageNotFoundError):
            await storage.read(path)

    asyncio.run(go())


def test_local_paths_match_the_original_module_functions(local_dir):
    document_id = uuid.uuid4()
    assert LocalStorage().generate_storage_path(document_id, "PDF") == local_storage.generate_storage_path(
        document_id, "PDF"
    )
    assert local_storage.generate_storage_path(document_id, "pdf").endswith(f"{document_id}.pdf")


def test_original_synchronous_functions_still_work(local_dir):
    path = local_storage.generate_storage_path(uuid.uuid4(), "txt")
    local_storage.save_file(path, b"abc")
    assert local_storage.read_file(path) == b"abc"
    local_storage.delete_file(path)
    local_storage.delete_file(path)
    assert not os.path.exists(path)


def test_local_save_refuses_paths_outside_the_storage_root(local_dir, tmp_path):
    with pytest.raises(StorageError, match="outside"):
        asyncio.run(LocalStorage().save(str(tmp_path / "elsewhere.txt"), b"x"))
    assert not (tmp_path / "elsewhere.txt").exists()


def test_legacy_file_outside_the_current_root_stays_readable(local_dir, tmp_path):
    """A document stored under an older DOCUMENT_STORAGE_PATH keeps working."""
    old_root = tmp_path / "old-root"
    old_root.mkdir()
    legacy = old_root / f"{uuid.uuid4()}.txt"
    legacy.write_bytes(b"from the old root")
    assert asyncio.run(get_storage_for_path(str(legacy)).read(str(legacy))) == b"from the old root"


# =========================================================================== parsers from bytes


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


@pytest.mark.parametrize(
    "file_type,content",
    [
        ("txt", ("Plain text body. " * 80).encode()),
        ("md", ("# Title\n\nSome *markdown* body.\n\n" * 40).encode()),
        ("pdf", make_pdf("Hello PDF world from bytes")),
        ("docx", make_docx("First paragraph of the document.", "Second paragraph here.")),
    ],
)
def test_bytes_and_path_ingestion_produce_identical_chunks(tmp_path, file_type, content):
    path = _write(tmp_path, f"doc.{file_type}", content)
    from_path = extract_chunks(path, file_type)
    from_bytes = extract_chunks_from_bytes(content, file_type)
    assert from_bytes == from_path
    assert len(from_bytes) > 0
    # And at the parser level too.
    assert parsers.parse_bytes(content, file_type) == parsers.parse(path, file_type)


def test_pdf_bytes_keep_page_numbers_and_text():
    (chunk,) = extract_chunks_from_bytes(make_pdf("Page one text"), "pdf")
    assert "Page one text" in chunk.text and chunk.page_number == 1


def test_docx_bytes_extract_paragraphs():
    (chunk,) = extract_chunks_from_bytes(make_docx("Alpha", "Beta"), "docx")
    assert "Alpha" in chunk.text and "Beta" in chunk.text


def test_chunk_size_overrides_apply_to_bytes_too():
    content = ("word " * 600).encode()
    small = extract_chunks_from_bytes(content, "txt", chunk_size=200, chunk_overlap=20)
    large = extract_chunks_from_bytes(content, "txt", chunk_size=2000, chunk_overlap=20)
    assert len(small) > len(large) >= 1


@pytest.mark.parametrize("file_type", ["txt", "md"])
def test_text_bytes_must_be_utf8_and_non_empty(file_type):
    with pytest.raises(parsers.ParsingError, match="UTF-8"):
        parsers.parse_bytes(b"\xff\xfe\x00bad", file_type)
    with pytest.raises(parsers.ParsingError, match="empty"):
        parsers.parse_bytes(b"   \n ", file_type)


@pytest.mark.parametrize("file_type,message", [("pdf", "Could not read PDF"), ("docx", "Could not read DOCX")])
def test_corrupt_binary_bytes_raise_parsing_error(file_type, message):
    with pytest.raises(parsers.ParsingError, match=message):
        parsers.parse_bytes(b"this is not a real file", file_type)


def test_unsupported_type_raises_parsing_error():
    with pytest.raises(parsers.ParsingError, match="Unsupported"):
        parsers.parse_bytes(b"x", "exe")


def test_path_parsers_keep_their_original_error_for_a_missing_file(tmp_path):
    for file_type, message in (("txt", "Could not read text"), ("md", "Could not read Markdown"),
                               ("pdf", "Could not read PDF"), ("docx", "Could not read DOCX")):
        with pytest.raises(parsers.ParsingError, match=message):
            parsers.parse(str(tmp_path / "missing"), file_type)


# =========================================================================== upload


def test_upload_to_r2_stores_a_uuid_keyed_object_and_nothing_locally(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session, filename="../../Secret Plan.txt")
            document = await get_document(world, session, created.id)
            return created, document

    created, document = scenario(go)
    key = f"documents/{created.id}.txt"
    assert document.storage_path == f"r2://{key}"
    assert r2_keys(fake_r2) == [key]  # keyed by UUID, never the client filename
    assert fake_r2.s3.objects[(BUCKET, key)] == TEXT
    assert "Secret" not in key and ".." not in key
    assert not os.path.exists(local_dir)


def test_upload_to_local_still_writes_an_absolute_path(local_dir, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "local")

    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            return (await get_document(world, session, created.id)).storage_path

    path = scenario(go)
    assert os.path.isabs(path) and not path.startswith("r2://")
    assert open(path, "rb").read() == TEXT


def test_upload_rolls_back_the_r2_object_if_the_database_fails(fake_r2, local_dir, monkeypatch):
    async def boom(self, document):
        raise RuntimeError("database down")

    monkeypatch.setattr(DocumentRepository, "create", boom)

    async def go(world):
        async with world.session_factory() as session:
            with pytest.raises(RuntimeError, match="database down"):
                await upload(world, session)

    scenario(go)
    assert fake_r2.s3.calls_for("put_object") and r2_keys(fake_r2) == []  # written, then removed
    assert len(fake_r2.s3.calls_for("delete_object")) == 1


def test_database_failure_rollback_never_touches_other_or_legacy_local_files(fake_r2, local_dir, monkeypatch):
    local_dir.mkdir(parents=True)
    legacy = local_dir / f"{uuid.uuid4()}.txt"
    legacy.write_bytes(b"legacy document that must survive")

    async def boom(self, document):
        raise RuntimeError("database down")

    monkeypatch.setattr(DocumentRepository, "create", boom)

    async def go(world):
        async with world.session_factory() as session:
            with pytest.raises(RuntimeError):
                await upload(world, session)

    scenario(go)
    assert legacy.read_bytes() == b"legacy document that must survive"
    assert local_files(local_dir) == [legacy.name]


def test_local_upload_rolls_back_its_file_if_the_database_fails(local_dir, monkeypatch):
    async def boom(self, document):
        raise RuntimeError("database down")

    monkeypatch.setattr(DocumentRepository, "create", boom)

    async def go(world):
        async with world.session_factory() as session:
            with pytest.raises(RuntimeError):
                await upload(world, session)

    scenario(go)
    assert local_files(local_dir) == []


def test_failed_r2_upload_stores_nothing_and_creates_no_record(fake_r2, local_dir):
    fake_r2.s3.fail["put_object"] = client_error("InternalError", "PutObject", 500)

    async def go(world):
        async with world.session_factory() as session:
            with pytest.raises(StorageError) as excinfo:
                await upload(world, session)
            documents = await DocumentRepository(session).get_by_workspace(world.workspace.id)
            return excinfo.value, documents

    error, documents = scenario(go)
    assert documents == [] and r2_keys(fake_r2) == []
    for secret in (SECRET_ACCESS_KEY, ACCESS_KEY_ID):
        assert secret not in str(error) and secret not in repr(error)


def test_oversized_upload_is_rejected_before_any_storage_call(fake_r2, local_dir, monkeypatch):
    from app.services.document_service import FileTooLargeError

    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "1")

    async def go(world):
        async with world.session_factory() as session:
            with pytest.raises(FileTooLargeError):
                await upload(world, session, content=b"x" * (1024 * 1024 + 1))

    scenario(go)
    assert fake_r2.s3.calls == []


# =========================================================================== reindex


def test_reindex_an_r2_document_reads_it_from_r2(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            result = await world.document_service(session).reindex_document_for_user(
                created.id, world.user.id
            )
            chunks = (await session.execute(select(Chunk).where(Chunk.document_id == created.id))).scalars().all()
            return created, result, chunks

    created, result, chunks = scenario(go)
    assert result.status == DocumentStatus.INDEXED and result.chunk_count == len(chunks) > 0
    assert fake_r2.s3.calls_for("get_object")
    assert not os.path.exists(local_dir)  # no local file was ever needed


def test_reindex_after_the_local_copy_is_gone_still_works_for_r2(fake_r2, local_dir):
    """The point of R2: reindexing needs no persistent local file."""
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            service = world.document_service(session)
            await service.reindex_document_for_user(created.id, world.user.id)
            fake_r2.s3.objects[(BUCKET, f"documents/{created.id}.txt")] = NEW_TEXT
            result = await service.reindex_document_for_user(created.id, world.user.id)
            texts = [c.content for c in (await session.execute(select(Chunk).where(Chunk.document_id == created.id))).scalars()]
            return result, texts

    result, texts = scenario(go)
    assert result.status == DocumentStatus.INDEXED
    assert all("revised body" in text for text in texts)  # the new object content was indexed


def test_reindex_a_legacy_local_document_while_r2_is_enabled(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            fake_r2.use_backend("local")  # the document predates R2
            created = await upload(world, session)
            fake_r2.use_backend("r2")  # R2 is now the configured backend
            result = await world.document_service(session).reindex_document_for_user(
                created.id, world.user.id
            )
            return created, result

    created, result = scenario(go)
    assert result.status == DocumentStatus.INDEXED and result.chunk_count > 0
    assert fake_r2.s3.calls == []  # served entirely from the local file
    assert len(local_files(local_dir)) == 1


@pytest.mark.parametrize("backend", ["local", "r2"])
def test_reindex_reads_each_supported_format_from_either_provider(fake_r2, local_dir, backend):
    fake_r2.use_backend(backend)
    samples = {
        "a.txt": TEXT,
        "b.md": b"# Heading\n\n" + TEXT,
        "c.pdf": make_pdf("Searchable PDF text"),
        "d.docx": make_docx("A docx paragraph about storage."),
    }

    async def go(world):
        async with world.session_factory() as session:
            outcome = {}
            for name, content in samples.items():
                created = await upload(world, session, filename=name, content=content)
                result = await world.document_service(session).reindex_document_for_user(
                    created.id, world.user.id
                )
                outcome[name] = (result.status, result.chunk_count)
            return outcome

    for name, (status, count) in scenario(go).items():
        assert status == DocumentStatus.INDEXED and count > 0, name


def test_reindex_with_a_missing_r2_object_marks_the_document_failed(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            fake_r2.s3.objects.clear()
            with pytest.raises(IngestionFailedError):
                await world.document_service(session).reindex_document_for_user(created.id, world.user.id)
            return (await get_document(world, session, created.id)).status

    assert scenario(go) == DocumentStatus.FAILED


def test_reindex_with_a_missing_local_file_marks_the_document_failed(local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            os.remove(os.path.join(local_dir, local_files(local_dir)[0]))
            with pytest.raises(IngestionFailedError):
                await world.document_service(session).reindex_document_for_user(created.id, world.user.id)
            return (await get_document(world, session, created.id)).status

    assert scenario(go) == DocumentStatus.FAILED


def test_failed_reindex_keeps_existing_chunks(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            service = world.document_service(session)
            await service.reindex_document_for_user(created.id, world.user.id)
            before = len((await session.execute(select(Chunk).where(Chunk.document_id == created.id))).scalars().all())
            fake_r2.s3.fail["get_object"] = client_error("InternalError", "GetObject", 500)
            with pytest.raises(IngestionFailedError):
                await service.reindex_document_for_user(created.id, world.user.id)
            after = len((await session.execute(select(Chunk).where(Chunk.document_id == created.id))).scalars().all())
            return before, after

    before, after = scenario(go)
    assert before == after > 0


# =========================================================================== delete


def test_delete_removes_the_r2_object_row_and_vectors(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            deleted = await world.document_service(session).delete_document_for_user(created.id, world.user.id)
            return created, deleted, await get_document(world, session, created.id)

    created, deleted, row = scenario(go)
    assert deleted is True and row is None
    assert r2_keys(fake_r2) == []


def test_delete_cleans_up_qdrant_for_r2_documents(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            await world.document_service(session).delete_document_for_user(created.id, world.user.id)
            return created.id, world.vector_store.deleted_document_ids

    document_id, deleted_ids = scenario(go)
    assert deleted_ids == [document_id]


def test_deleting_a_legacy_local_document_while_r2_is_enabled_removes_only_that_local_file(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            fake_r2.use_backend("local")
            legacy = await upload(world, session, filename="legacy.txt")
            other_legacy = await upload(world, session, filename="other.txt")
            fake_r2.use_backend("r2")
            r2_doc = await upload(world, session, filename="new.txt")
            await world.document_service(session).delete_document_for_user(legacy.id, world.user.id)
            return legacy, other_legacy, r2_doc

    legacy, other_legacy, r2_doc = scenario(go)
    remaining = local_files(local_dir)
    assert remaining == [f"{other_legacy.id}.txt"]  # the other legacy file was NOT touched
    assert r2_keys(fake_r2) == [f"documents/{r2_doc.id}.txt"]  # nor was the R2 object
    assert fake_r2.s3.calls_for("delete_object") == []


def test_deleting_an_r2_document_never_touches_local_files(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            fake_r2.use_backend("local")
            legacy = await upload(world, session, filename="legacy.txt")
            fake_r2.use_backend("r2")
            r2_doc = await upload(world, session, filename="new.txt")
            await world.document_service(session).delete_document_for_user(r2_doc.id, world.user.id)
            return legacy

    legacy = scenario(go)
    assert local_files(local_dir) == [f"{legacy.id}.txt"]
    assert r2_keys(fake_r2) == []


def test_delete_succeeds_even_if_the_object_is_already_missing(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            fake_r2.s3.objects.clear()
            return await world.document_service(session).delete_document_for_user(created.id, world.user.id)

    assert scenario(go) is True


def test_delete_still_succeeds_if_r2_fails_and_logs_without_secrets(fake_r2, local_dir, caplog):
    async def go(world):
        async with world.session_factory() as session:
            created = await upload(world, session)
            fake_r2.s3.fail["delete_object"] = client_error("InternalError", "DeleteObject", 500)
            with caplog.at_level(logging.DEBUG):
                deleted = await world.document_service(session).delete_document_for_user(created.id, world.user.id)
            return deleted, await get_document(world, session, created.id)

    deleted, row = scenario(go)
    assert deleted is True and row is None  # the database row is gone regardless
    assert "Could not delete stored document file" in caplog.text
    assert SECRET_ACCESS_KEY not in caplog.text and ACCESS_KEY_ID not in caplog.text


def test_delete_stored_file_reports_whether_the_object_is_gone(fake_r2, local_dir):
    async def go():
        storage = get_storage_for_new_documents()
        ref = storage.generate_storage_path(uuid.uuid4(), "txt")
        await storage.save(ref, b"x")
        assert await delete_stored_file(ref) is True
        assert await delete_stored_file(ref) is True  # missing counts as gone
        fake_r2.s3.fail["delete_object"] = client_error("AccessDenied", "DeleteObject", 403)
        assert await delete_stored_file(ref) is False

    asyncio.run(go())


# =========================================================================== workspace deletion


def test_workspace_deletion_cleans_up_r2_and_legacy_local_files_and_vectors(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            fake_r2.use_backend("local")
            legacy = await upload(world, session, filename="legacy.txt")
            fake_r2.use_backend("r2")
            r2_doc = await upload(world, session, filename="new.txt")
            deleted = await world.workspace_service(session).delete_workspace_for_user(
                world.workspace.id, world.user.id
            )
            return legacy, r2_doc, deleted, world.vector_store.deleted_document_ids

    legacy, r2_doc, deleted, vector_ids = scenario(go)
    assert deleted is True
    assert r2_keys(fake_r2) == []
    assert local_files(local_dir) == []
    assert sorted(vector_ids, key=str) == sorted([legacy.id, r2_doc.id], key=str)


def test_workspace_deletion_survives_an_r2_failure(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            await upload(world, session)
            fake_r2.s3.fail["delete_object"] = client_error("InternalError", "DeleteObject", 500)
            return await world.workspace_service(session).delete_workspace_for_user(
                world.workspace.id, world.user.id
            )

    assert scenario(go) is True


# =========================================================================== GitHub sync


def github_file(content: bytes, sha: str, path="docs/guide.txt") -> GitHubFile:
    return GitHubFile(
        repository="octocat/Hello-World", branch="main", path=path, filename=path.rsplit("/", 1)[-1],
        content=content, sha=sha, url=f"https://github.com/octocat/Hello-World/blob/main/{path}",
        size=len(content),
    )


async def chunk_metadata(session, document_id):
    rows = (await session.execute(select(Chunk).where(Chunk.document_id == document_id))).scalars().all()
    return rows, {row.metadata_.get("github_sha") for row in rows}, {row.metadata_.get("drive_modified_time") for row in rows}


@pytest.mark.parametrize("origin", ["r2", "legacy"])
def test_github_changed_file_overwrites_in_place_with_the_owning_provider(fake_r2, local_dir, origin):
    async def go(world):
        async with world.session_factory() as session:
            fake_r2.use_backend("local" if origin == "legacy" else "r2")
            service = world.connector_service(session)
            original = github_file(TEXT, "sha-1")
            assert await service._ingest_github_file(
                world.connector, world.user.id, original, existing_document_id=None
            ) is True
            document = await DocumentRepository(session).get_by_workspace_and_filename(
                world.workspace.id, "docs/guide.txt"
            )
            before_path, before_id = document.storage_path, document.id

            fake_r2.use_backend("r2")  # R2 is the configured backend from now on
            changed = github_file(NEW_TEXT, "sha-2")
            assert await service._ingest_github_file(
                world.connector, world.user.id, changed, existing_document_id=document.id
            ) is True

            refreshed = await get_document(world, session, before_id)
            rows, shas, _ = await chunk_metadata(session, before_id)
            return before_path, before_id, refreshed, rows, shas

    before_path, before_id, refreshed, rows, shas = scenario(go)
    assert refreshed.id == before_id and refreshed.storage_path == before_path  # same document, same location
    assert refreshed.file_size == len(NEW_TEXT) and refreshed.status == DocumentStatus.INDEXED
    assert shas == {"sha-2"} and all("revised body" in row.content for row in rows)
    if origin == "r2":
        assert fake_r2.s3.objects[(BUCKET, before_path[len("r2://"):])] == NEW_TEXT
        assert not os.path.exists(local_dir)
    else:
        assert open(before_path, "rb").read() == NEW_TEXT  # the legacy file was updated locally
        assert r2_keys(fake_r2) == []  # and nothing was copied into R2


def test_github_new_file_is_stored_in_r2_when_enabled(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            ok = await world.connector_service(session)._ingest_github_file(
                world.connector, world.user.id, github_file(TEXT, "sha-1"), existing_document_id=None
            )
            document = await DocumentRepository(session).get_by_workspace_and_filename(world.workspace.id, "docs/guide.txt")
            return ok, document

    ok, document = scenario(go)
    assert ok is True and document.connector_id is not None
    assert document.storage_path == f"r2://documents/{document.id}.txt"
    assert r2_keys(fake_r2) == [f"documents/{document.id}.txt"]


def test_github_overwrite_failure_counts_the_file_as_failed_and_keeps_the_old_content(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            service = world.connector_service(session)
            assert await service._ingest_github_file(
                world.connector, world.user.id, github_file(TEXT, "sha-1"), existing_document_id=None
            )
            document = await DocumentRepository(session).get_by_workspace_and_filename(world.workspace.id, "docs/guide.txt")
            fake_r2.s3.fail["put_object"] = client_error("InternalError", "PutObject", 500)
            ok = await service._ingest_github_file(
                world.connector, world.user.id, github_file(NEW_TEXT, "sha-2"), existing_document_id=document.id
            )
            return ok, document

    ok, document = scenario(go)
    assert ok is False  # reported as a failed file, not an exception that aborts the whole sync
    assert fake_r2.s3.objects[(BUCKET, f"documents/{document.id}.txt")] == TEXT


# =========================================================================== Google Drive sync


def drive_file(content: bytes, modified: str, file_id="drive-file-1") -> GoogleDriveFetchedFile:
    return GoogleDriveFetchedFile(
        file_id=file_id, filename="report.txt", content=content, file_type="txt",
        mime_type="text/plain", size=len(content), modified_time=modified,
        web_view_link=f"https://drive.google.com/file/d/{file_id}/view",
    )


@pytest.mark.parametrize("origin", ["r2", "legacy"])
def test_drive_changed_file_overwrites_in_place_with_the_owning_provider(fake_r2, local_dir, origin):
    async def go(world):
        async with world.session_factory() as session:
            fake_r2.use_backend("local" if origin == "legacy" else "r2")
            service = world.connector_service(session)
            assert await service._ingest_google_drive_file(
                world.connector, world.user.id, drive_file(TEXT, "2026-01-01T00:00:00Z")
            ) is True
            document = await DocumentRepository(session).get_by_workspace_and_filename(world.workspace.id, "report.txt")
            before_path, before_id = document.storage_path, document.id

            fake_r2.use_backend("r2")
            assert await service._ingest_google_drive_file(
                world.connector, world.user.id, drive_file(NEW_TEXT, "2026-02-02T00:00:00Z"),
                existing_document_id=document.id,
            ) is True
            refreshed = await get_document(world, session, before_id)
            rows, _, modified = await chunk_metadata(session, before_id)
            return before_path, before_id, refreshed, rows, modified

    before_path, before_id, refreshed, rows, modified = scenario(go)
    assert refreshed.id == before_id and refreshed.storage_path == before_path
    assert refreshed.file_size == len(NEW_TEXT) and refreshed.status == DocumentStatus.INDEXED
    assert modified == {"2026-02-02T00:00:00Z"} and all("revised body" in row.content for row in rows)
    if origin == "r2":
        assert fake_r2.s3.objects[(BUCKET, before_path[len("r2://"):])] == NEW_TEXT
        assert not os.path.exists(local_dir)
    else:
        assert open(before_path, "rb").read() == NEW_TEXT
        assert r2_keys(fake_r2) == []


def test_drive_new_file_is_stored_in_r2_with_its_drive_identity(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            ok = await world.connector_service(session)._ingest_google_drive_file(
                world.connector, world.user.id, drive_file(TEXT, "2026-01-01T00:00:00Z")
            )
            document = await DocumentRepository(session).get_by_workspace_and_filename(world.workspace.id, "report.txt")
            return ok, document

    ok, document = scenario(go)
    assert ok is True and document.source_id == "drive-file-1"
    assert r2_keys(fake_r2) == [f"documents/{document.id}.txt"]


def test_drive_overwrite_failure_counts_the_file_as_failed(fake_r2, local_dir):
    async def go(world):
        async with world.session_factory() as session:
            service = world.connector_service(session)
            await service._ingest_google_drive_file(world.connector, world.user.id, drive_file(TEXT, "t1"))
            document = await DocumentRepository(session).get_by_workspace_and_filename(world.workspace.id, "report.txt")
            fake_r2.s3.fail["put_object"] = client_error("AccessDenied", "PutObject", 403)
            return await service._ingest_google_drive_file(
                world.connector, world.user.id, drive_file(NEW_TEXT, "t2"), existing_document_id=document.id
            )

    assert scenario(go) is False


# =========================================================================== no secrets


def test_full_upload_reindex_delete_cycle_leaks_no_credentials(fake_r2, local_dir, caplog):
    async def go(world):
        async with world.session_factory() as session:
            with caplog.at_level(logging.DEBUG):
                created = await upload(world, session)
                service = world.document_service(session)
                await service.reindex_document_for_user(created.id, world.user.id)
                fake_r2.s3.fail["delete_object"] = client_error("AccessDenied", "DeleteObject", 403)
                await service.delete_document_for_user(created.id, world.user.id)

    scenario(go)
    assert SECRET_ACCESS_KEY not in caplog.text and ACCESS_KEY_ID not in caplog.text
