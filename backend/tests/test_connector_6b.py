"""Wave 6B regression tests: Google Drive file fetching + ingestion
(POST /connectors/{id}/sync/google-drive, GoogleDriveConnector.fetch_file,
ConnectorService.sync_google_drive).

Mirrors test_connector_sync_wave5b.py/test_connector_sync_5c.py's
structure and conventions for GitHub sync. All Google Drive API calls
are mocked - no real access token or network access is used or
required. Uses real pypdf/python-docx to build small, genuinely
parseable PDF/DOCX byte content, since these tests exercise the real
DocumentService ingestion pipeline (parsing, chunking, embedding, and
Qdrant indexing via a mock vector store) end to end, not just the
Google Drive connector in isolation.
"""

import asyncio
import shutil
import tempfile
import uuid
from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chunk  # noqa: F401
import app.models.connector  # noqa: F401
import app.models.document  # noqa: F401
import app.models.user  # noqa: F401
import app.models.workspace  # noqa: F401
import app.services.document_service as document_service_module
import main
from app.api.v1.connectors.router import get_connector_service
from app.auth.dependencies import get_current_user
from app.connectors import google_drive_connector as google_drive_connector_module
from app.database.base import Base
from app.database.session import get_db
from app.models.document import DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.connector_service import ConnectorNotFoundError, ConnectorService
from app.services.document_service import DocumentService


def _fake_embed_texts(texts):
    """Stands in for the real BAAI/bge-m3 embedding model, which these
    tests never load (no network/model cache access is assumed) -
    mirrors tests/test_connector_sync_wave5b.py's identical fake.
    """
    return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture(autouse=True)
def _temp_storage_and_fake_embeddings(monkeypatch):
    """Redirects document storage to a throwaway temp directory (so
    these tests never write into the repo's real storage/ directory)
    and replaces the real embedding model with `_fake_embed_texts`,
    for every test in this module - mirrors the identical autouse
    fixture in tests/test_connector_sync_wave5b.py.
    """
    temp_dir = tempfile.mkdtemp(prefix="lumora-test-storage-")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", temp_dir)
    monkeypatch.setattr(document_service_module, "embed_texts", _fake_embed_texts)
    yield
    shutil.rmtree(temp_dir, ignore_errors=True)


def _make_pdf_bytes(text: str) -> bytes:
    """A hand-built, minimal-but-genuinely-parseable single-page PDF
    containing `text` as extractable content - short enough to inline
    here, real enough for pypdf (via app.ingestion.parsers.pdf_parser)
    to actually extract text from, which is what these tests need to
    exercise real ingestion rather than a parsing stub.
    """
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


def _make_docx_bytes(text: str) -> bytes:
    buf = BytesIO()
    docx_document = DocxDocument()
    docx_document.add_paragraph(text)
    docx_document.save(buf)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None, content: bytes = b""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.content = content

    def json(self):
        return self._json_data


def _install_fake_drive_api(
    monkeypatch,
    *,
    discovery_files,
    downloads=None,
    exports=None,
    download_statuses=None,
    export_statuses=None,
    about_status=200,
):
    """Patches google_drive_connector.requests.get to fake every Drive
    endpoint this wave's code calls: /about (token validation),
    /files/{id} (root folder validation, default response only),
    /files (discovery listing), /files/{id}?alt=media (binary
    download - keyed by file_id in `downloads`), and
    /files/{id}/export (Google-native export - keyed by file_id in
    `exports`, regardless of the requested export mimeType).
    """
    downloads = downloads or {}
    exports = exports or {}
    download_statuses = download_statuses or {}
    export_statuses = export_statuses or {}

    def fake_get(url, headers=None, params=None, timeout=None):
        params = params or {}
        if url.endswith("/about"):
            return _FakeResponse(
                about_status, {"user": {"emailAddress": "user@example.com"}}
            )
        if url.endswith("/export"):
            file_id = url.rsplit("/files/", 1)[1].rsplit("/export", 1)[0]
            status = export_statuses.get(file_id, 200)
            return _FakeResponse(status, content=exports.get(file_id, b""))
        if params.get("alt") == "media":
            file_id = url.rsplit("/files/", 1)[1]
            status = download_statuses.get(file_id, 200)
            return _FakeResponse(status, content=downloads.get(file_id, b""))
        if url.endswith("/files"):
            return _FakeResponse(200, {"files": discovery_files})
        # Root folder validation (GET /files/{id} with no alt/export) -
        # not exercised by these tests (no connector here uses
        # root_folder_id), but answered generically in case that changes.
        file_id = url.rsplit("/files/", 1)[-1]
        return _FakeResponse(
            200, {"id": file_id, "name": "folder", "mimeType": "application/vnd.google-apps.folder"}
        )

    monkeypatch.setattr(google_drive_connector_module.requests, "get", fake_get)


class _FakeVectorStore:
    """A minimal QdrantVectorStore stand-in: records upserts/deletes in
    memory instead of talking to a real Qdrant instance, so these
    tests exercise DocumentService's real reindex logic (including its
    vector-store calls) without any external service.
    """

    def __init__(self):
        self.points_by_document = {}

    async def upsert_chunks(self, points):
        for point in points:
            self.points_by_document.setdefault(point.document_id, []).append(point)

    async def delete_document_chunks(self, document_id):
        self.points_by_document.pop(document_id, None)


async def _make_engine_and_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _seed_two_users_with_workspaces(session_factory):
    async with session_factory() as session:
        user_a = User(id=uuid4(), email="a@example.com", name="A")
        user_b = User(id=uuid4(), email="b@example.com", name="B")
        workspace_a = Workspace(id=uuid4(), user_id=user_a.id, name="WS-A")
        workspace_b = Workspace(id=uuid4(), user_id=user_b.id, name="WS-B")
        session.add_all([user_a, user_b, workspace_a, workspace_b])
        await session.commit()
        return user_a, user_b, workspace_a, workspace_b


def _make_connector_service(session, vector_store=None):
    document_service = DocumentService(
        DocumentRepository(session), WorkspaceRepository(session),
        ChunkRepository(session), vector_store=vector_store or _FakeVectorStore(),
    )
    return ConnectorService(
        ConnectorRepository(session), WorkspaceRepository(session), document_service
    )


async def _create_google_drive_connector(service, user, workspace):
    return await service.connect_google_drive(
        user_id=user.id, workspace_id=workspace.id, access_token="tok",
    )


def test_binary_file_download_and_ingestion(monkeypatch):
    """A, D, E, G: an ordinary PDF is downloaded, ingested through the
    real DocumentService pipeline (parsed/chunked/embedded/indexed),
    and its Document correctly owned and identified.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        pdf_bytes = _make_pdf_bytes("The quarterly report is attached.")
        _install_fake_drive_api(
            monkeypatch,
            discovery_files=[
                {"id": "pdf-1", "name": "report.pdf", "mimeType": "application/pdf",
                 "size": str(len(pdf_bytes)), "webViewLink": "https://drive.google.com/file/d/pdf-1"},
            ],
            downloads={"pdf-1": pdf_bytes},
        )

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            summary = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert summary.files_discovered == 1
            assert summary.files_added == 1
            assert summary.files_failed == 0
            assert summary.status == "completed"

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents) == 1
            document = documents[0]
            assert document.workspace_id == workspace_a.id
            assert document.connector_id == connector.id
            assert document.source_id == "pdf-1"
            assert document.file_type == "pdf"
            assert document.status == DocumentStatus.INDEXED
            assert document.chunk_count > 0

        await engine.dispose()

    asyncio.run(_run())


@pytest.mark.parametrize(
    "mime_type,expected_extension",
    [
        ("application/vnd.google-apps.document", "docx"),
        ("application/vnd.google-apps.spreadsheet", "pdf"),
        ("application/vnd.google-apps.presentation", "pdf"),
    ],
)
def test_google_native_export_and_ingestion(monkeypatch, mime_type, expected_extension):
    """B, G: Google Docs/Sheets/Slides are exported to a
    DocumentService-ingestible format and successfully indexed.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        if expected_extension == "docx":
            export_bytes = _make_docx_bytes("Exported Google Doc content.")
        else:
            export_bytes = _make_pdf_bytes("Exported Google file content.")

        _install_fake_drive_api(
            monkeypatch,
            discovery_files=[
                {"id": "native-1", "name": "Design Doc", "mimeType": mime_type},
            ],
            exports={"native-1": export_bytes},
        )

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            summary = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert summary.files_added == 1
            assert summary.files_failed == 0

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents) == 1
            document = documents[0]
            assert document.file_type == expected_extension
            assert document.filename.endswith(f".{expected_extension}")
            assert document.source_id == "native-1"
            assert document.status == DocumentStatus.INDEXED

        await engine.dispose()

    asyncio.run(_run())


def test_unsupported_file_is_skipped(monkeypatch):
    """C: a file of a type DocumentService can't ingest (and that
    isn't a Google-native format) is skipped, not imported or failed.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _install_fake_drive_api(
            monkeypatch,
            discovery_files=[
                {"id": "zip-1", "name": "archive.zip", "mimeType": "application/zip"},
                {"id": "folder-1", "name": "Subfolder", "mimeType": "application/vnd.google-apps.folder"},
            ],
        )

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            summary = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )

            assert summary.files_discovered == 2
            assert summary.files_added == 0
            assert summary.files_skipped == 1
            assert any("archive.zip" in note for note in summary.notes)

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert documents == []

        await engine.dispose()

    asyncio.run(_run())


def test_duplicate_sync_does_not_create_second_document(monkeypatch):
    """F: running sync twice for the same connector + Drive file ID
    imports once, then recognizes it as already imported.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        pdf_bytes = _make_pdf_bytes("Idempotent import test content.")
        _install_fake_drive_api(
            monkeypatch,
            discovery_files=[
                {"id": "pdf-dup", "name": "notes.pdf", "mimeType": "application/pdf",
                 "modifiedTime": "2026-01-01T00:00:00Z"},
            ],
            downloads={"pdf-dup": pdf_bytes},
        )

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            first = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            assert first.files_added == 1
            assert first.files_unchanged == 0

            second = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            assert second.files_added == 0
            assert second.files_unchanged == 1

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents) == 1

        await engine.dispose()

    asyncio.run(_run())


def test_failed_file_is_reported_and_others_still_import(monkeypatch):
    """H: one file that fails to fetch is reported as failed/skipped
    without aborting the rest of the sync.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        good_pdf = _make_pdf_bytes("This one fetches fine.")
        _install_fake_drive_api(
            monkeypatch,
            discovery_files=[
                {"id": "pdf-good", "name": "good.pdf", "mimeType": "application/pdf"},
                {"id": "pdf-bad", "name": "bad.pdf", "mimeType": "application/pdf"},
            ],
            downloads={"pdf-good": good_pdf},
            download_statuses={"pdf-bad": 500},
        )

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            summary = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert summary.files_discovered == 2
            assert summary.files_added == 1
            assert summary.files_skipped == 1
            assert any("bad.pdf" in note for note in summary.notes)

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents) == 1
            assert documents[0].source_id == "pdf-good"

        await engine.dispose()

    asyncio.run(_run())


def test_no_credential_leakage_into_documents_chunks_or_responses(monkeypatch):
    """I: the access token never appears in the sync response, in the
    Document's stored fields, or in any chunk's metadata.
    """
    async def _setup():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        return engine, session_factory, user_a, workspace_a

    engine, session_factory, user_a, workspace_a = asyncio.run(_setup())
    secret_token = "ya29.super_secret_drive_access_token"
    pdf_bytes = _make_pdf_bytes("Nothing secret in here.")
    _install_fake_drive_api(
        monkeypatch,
        discovery_files=[
            {"id": "pdf-secure", "name": "secure.pdf", "mimeType": "application/pdf"},
        ],
        downloads={"pdf-secure": pdf_bytes},
    )

    current_user_holder = {"user": user_a}

    async def override_get_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    async def override_get_current_user():
        return current_user_holder["user"]

    async def override_get_connector_service():
        async with session_factory() as session:
            yield _make_connector_service(session)
            await session.commit()

    main.app.dependency_overrides[get_db] = override_get_db
    main.app.dependency_overrides[get_current_user] = override_get_current_user
    main.app.dependency_overrides[get_connector_service] = override_get_connector_service

    try:
        client = TestClient(main.app)

        create_resp = client.post("/api/v1/connectors/google-drive", json={
            "workspace_id": str(workspace_a.id), "access_token": secret_token,
        })
        assert create_resp.status_code == 201
        connector_id = create_resp.json()["id"]
        assert secret_token not in create_resp.text

        sync_resp = client.post(
            f"/api/v1/connectors/{connector_id}/sync/google-drive",
            json={"access_token": secret_token},
        )
        assert sync_resp.status_code == 200
        assert sync_resp.json()["files_added"] == 1
        assert secret_token not in sync_resp.text

        async def _check_no_token_in_storage():
            async with session_factory() as session:
                documents = await DocumentRepository(session).get_by_connector(
                    uuid.UUID(connector_id)
                )
                assert len(documents) == 1
                document = documents[0]
                assert secret_token not in str(document.__dict__)

                metadata = await ChunkRepository(session).get_metadata_sample(document.id)
                assert metadata is not None
                assert secret_token not in str(metadata)
                assert "access_token" not in metadata
                assert metadata["origin"] == "google_drive"
                assert metadata["drive_file_id"] == "pdf-secure"

        asyncio.run(_check_no_token_in_storage())
    finally:
        main.app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_sync_is_connector_and_workspace_isolated(monkeypatch):
    """J: syncing a connector requires owning its workspace; another
    user gets ConnectorNotFoundError, never another workspace's data.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _install_fake_drive_api(monkeypatch, discovery_files=[])

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            with pytest.raises(ConnectorNotFoundError):
                await service.sync_google_drive(
                    connector_id=connector.id, user_id=user_b.id, access_token="tok",
                )

        await engine.dispose()

    asyncio.run(_run())
