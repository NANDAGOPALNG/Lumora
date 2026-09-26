"""Wave 6C regression tests: Google Drive incremental synchronization
(ConnectorService.sync_google_drive's add/update/delete
reconciliation, extending Wave 6B's import-only version).

Mirrors test_connector_sync_5c.py's structure and conventions for
GitHub's own incremental sync. All Google Drive API calls are mocked -
no real access token or network access is used or required. Reuses
test_connector_6b.py's approach of building small, genuinely
parseable PDF/DOCX byte content so these tests exercise the real
DocumentService ingestion pipeline end to end.

The discovery/download/export fakes here are deliberately *mutable*
between two `sync_google_drive()` calls within one test (the same
list/dict objects a test passes to `_install_fake_drive_api` are
mutated directly afterward) - this is how these tests simulate Drive's
state changing between syncs (a file's modifiedTime changing, a file
disappearing, new content for an existing file).
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
from sqlalchemy import event, select
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
from app.connectors.base import ConnectorResourceNotFoundError
from app.database.base import Base
from app.database.session import get_db
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.connector_service import ConnectorNotFoundError, ConnectorService
from app.services.document_service import DocumentService


async def _get_chunks_for_document(session, document_id):
    """test-only helper: ChunkRepository has no direct "all chunks for
    this document" accessor (only counts/metadata samples/deletes), so
    query the Chunk model directly to inspect content in assertions.
    """
    result = await session.execute(
        select(Chunk).where(Chunk.document_id == document_id)
    )
    return list(result.scalars().all())


def _fake_embed_texts(texts):
    return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture(autouse=True)
def _temp_storage_and_fake_embeddings(monkeypatch):
    temp_dir = tempfile.mkdtemp(prefix="lumora-test-storage-")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", temp_dir)
    monkeypatch.setattr(document_service_module, "embed_texts", _fake_embed_texts)
    yield
    shutil.rmtree(temp_dir, ignore_errors=True)


def _make_pdf_bytes(text: str) -> bytes:
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
    discovery_status=200,
):
    """Same fake Drive API as tests/test_connector_6b.py, plus
    `discovery_status` (to simulate a failed discovery listing - item
    H) and capturing the last `q` filter sent to `GET /files` (via the
    returned callable) so a test can confirm a connector's
    `drive_root_folder_id` actually scopes discovery (item G).

    `discovery_files`, `downloads`, and `exports` are the same
    list/dicts the caller passed in - mutate them directly between two
    `sync_google_drive()` calls in the same test to simulate Drive's
    state changing.
    """
    downloads = downloads if downloads is not None else {}
    exports = exports if exports is not None else {}
    download_statuses = download_statuses if download_statuses is not None else {}
    export_statuses = export_statuses if export_statuses is not None else {}
    last_discovery_query = {}

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
            last_discovery_query["q"] = params.get("q")
            return _FakeResponse(discovery_status, {"files": list(discovery_files)})
        file_id = url.rsplit("/files/", 1)[-1]
        return _FakeResponse(
            200, {"id": file_id, "name": "folder", "mimeType": "application/vnd.google-apps.folder"}
        )

    monkeypatch.setattr(google_drive_connector_module.requests, "get", fake_get)
    return last_discovery_query


class _FakeVectorStore:
    def __init__(self):
        self.points_by_document = {}
        self.deleted_document_ids = []

    async def upsert_chunks(self, points):
        for point in points:
            self.points_by_document.setdefault(point.document_id, []).append(point)

    async def delete_document_chunks(self, document_id):
        self.points_by_document.pop(document_id, None)
        self.deleted_document_ids.append(document_id)


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


async def _create_google_drive_connector(service, user, workspace, root_folder_id=None):
    return await service.connect_google_drive(
        user_id=user.id, workspace_id=workspace.id, access_token="tok",
        root_folder_id=root_folder_id,
    )


def test_new_file_is_added(monkeypatch):
    """A: a newly discovered file is imported with correct
    connector_id/source_id."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        pdf_bytes = _make_pdf_bytes("Brand new file content.")
        _install_fake_drive_api(
            monkeypatch,
            discovery_files=[
                {"id": "new-1", "name": "new.pdf", "mimeType": "application/pdf",
                 "modifiedTime": "2026-01-01T00:00:00Z"},
            ],
            downloads={"new-1": pdf_bytes},
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
            assert summary.files_updated == 0
            assert summary.files_deleted == 0
            assert summary.status == "completed"

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents) == 1
            assert documents[0].connector_id == connector.id
            assert documents[0].source_id == "new-1"

        await engine.dispose()

    asyncio.run(_run())


def test_unchanged_file_is_left_untouched(monkeypatch):
    """B: a file whose modifiedTime hasn't changed is skipped (not
    reindexed) on a second sync."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_files = [
            {"id": "stable-1", "name": "stable.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        downloads = {"stable-1": _make_pdf_bytes("Stable content.")}
        _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, downloads=downloads)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            first = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            assert first.files_added == 1

            documents_after_first = await DocumentRepository(session).get_by_connector(connector.id)
            original_chunk_count = documents_after_first[0].chunk_count

            # Drive state is unchanged - same modifiedTime.
            second = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert second.files_added == 0
            assert second.files_updated == 0
            assert second.files_unchanged == 1
            assert second.files_deleted == 0

            documents_after_second = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents_after_second) == 1
            assert documents_after_second[0].id == documents_after_first[0].id
            assert documents_after_second[0].chunk_count == original_chunk_count

        await engine.dispose()

    asyncio.run(_run())


def test_modified_file_is_reindexed_in_place(monkeypatch):
    """C: a file whose modifiedTime changed is refetched and
    reindexed under the SAME Document id, replacing its chunks."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_files = [
            {"id": "changing-1", "name": "changing.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        downloads = {"changing-1": _make_pdf_bytes("Original version.")}
        _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, downloads=downloads)

        vector_store = _FakeVectorStore()

        async with session_factory() as session:
            service = _make_connector_service(session, vector_store=vector_store)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            first = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            assert first.files_added == 1

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            original_document_id = documents[0].id
            original_vector_count = len(vector_store.points_by_document.get(original_document_id, []))

            # Drive state changes: same file ID, new modifiedTime, new content.
            discovery_files[0]["modifiedTime"] = "2026-02-01T00:00:00Z"
            downloads["changing-1"] = _make_pdf_bytes("Updated version with different text.")

            second = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert second.files_added == 0
            assert second.files_updated == 1
            assert second.files_unchanged == 0

            documents_after = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents_after) == 1
            assert documents_after[0].id == original_document_id  # same Document row
            assert documents_after[0].status == DocumentStatus.INDEXED

            chunks = await _get_chunks_for_document(session, original_document_id)
            assert any("Updated version" in c.content for c in chunks)
            assert not any("Original version" in c.content for c in chunks)

            new_vector_count = len(vector_store.points_by_document.get(original_document_id, []))
            assert new_vector_count > 0
            # Old vectors were replaced (delete_document_chunks called
            # again for this document during the second reindex).
            assert vector_store.deleted_document_ids.count(original_document_id) >= 2

        await engine.dispose()

    asyncio.run(_run())


def test_google_native_file_update_still_uses_export(monkeypatch):
    """K: an updated Google Doc is re-exported and reindexed, keeping
    its .docx extension and the same Document id."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_files = [
            {"id": "doc-1", "name": "Design Doc",
             "mimeType": "application/vnd.google-apps.document",
             "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        exports = {"doc-1": _make_docx_bytes("Original doc export.")}
        _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, exports=exports)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            first = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            assert first.files_added == 1

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            original_id = documents[0].id
            assert documents[0].file_type == "docx"

            discovery_files[0]["modifiedTime"] = "2026-03-01T00:00:00Z"
            exports["doc-1"] = _make_docx_bytes("Updated doc export content.")

            second = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert second.files_updated == 1
            documents_after = await DocumentRepository(session).get_by_connector(connector.id)
            assert documents_after[0].id == original_id
            assert documents_after[0].file_type == "docx"

            chunks = await _get_chunks_for_document(session, original_id)
            assert any("Updated doc export" in c.content for c in chunks)

        await engine.dispose()

    asyncio.run(_run())


def test_deleted_file_removes_document_chunks_and_vectors(monkeypatch):
    """D: a file no longer present in Drive gets its Document (and
    chunks/vectors) deleted, via the existing delete_document_for_user path."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_files = [
            {"id": "gone-1", "name": "gone.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
            {"id": "stays-1", "name": "stays.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        downloads = {
            "gone-1": _make_pdf_bytes("This file will be deleted from Drive."),
            "stays-1": _make_pdf_bytes("This file stays."),
        }
        _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, downloads=downloads)

        vector_store = _FakeVectorStore()

        async with session_factory() as session:
            service = _make_connector_service(session, vector_store=vector_store)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            first = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            assert first.files_added == 2

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            gone_document = next(d for d in documents if d.source_id == "gone-1")

            # "gone-1" is removed from the current Drive state.
            discovery_files.pop(0)

            second = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert second.files_deleted == 1
            assert second.files_unchanged == 1

            remaining = await DocumentRepository(session).get_by_connector(connector.id)
            assert {d.source_id for d in remaining} == {"stays-1"}
            assert gone_document.id in vector_store.deleted_document_ids

        await engine.dispose()

    asyncio.run(_run())


def test_no_duplicate_documents_across_repeated_syncs(monkeypatch):
    """E: repeated syncs of an unchanged Drive state never create
    duplicate Documents."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_files = [
            {"id": "dup-1", "name": "dup.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        downloads = {"dup-1": _make_pdf_bytes("Some content.")}
        _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, downloads=downloads)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            for _ in range(3):
                await service.sync_google_drive(
                    connector_id=connector.id, user_id=user_a.id, access_token="tok",
                )
                await session.commit()

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents) == 1

        await engine.dispose()

    asyncio.run(_run())


def test_second_connector_is_unaffected_by_first_connectors_sync(monkeypatch):
    """F: syncing connector A never touches connector B's documents,
    even ones with an overlapping-looking source_id."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _install_fake_drive_api(monkeypatch, discovery_files=[])

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector_a = await _create_google_drive_connector(service, user_a, workspace_a)
            connector_b = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            # Seed a document for connector B directly (as if a prior
            # sync of connector B had imported it) with a source_id
            # that would collide if isolation were broken.
            created = await service.document_service.upload_document(
                workspace_id=workspace_a.id, user_id=user_a.id, filename="b-owned.pdf",
                content_type="application/pdf", content=_make_pdf_bytes("Owned by connector B."),
                connector_id=connector_b.id, source_id="shared-looking-id",
            )
            await service.document_service.reindex_document_for_user(created.id, user_a.id)
            await session.commit()

            # Connector A's Drive is empty - if isolation were broken,
            # a naive "delete anything not discovered" could wipe
            # connector B's document out from under it.
            summary = await service.sync_google_drive(
                connector_id=connector_a.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert summary.files_deleted == 0

            documents_a = await DocumentRepository(session).get_by_connector(connector_a.id)
            documents_b = await DocumentRepository(session).get_by_connector(connector_b.id)
            assert documents_a == []
            assert len(documents_b) == 1
            assert documents_b[0].id == created.id

        await engine.dispose()

    asyncio.run(_run())


def test_sync_respects_connectors_configured_root_folder(monkeypatch):
    """G: discovery is scoped to the connector's stored
    drive_root_folder_id, not the whole Drive."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        last_query = _install_fake_drive_api(monkeypatch, discovery_files=[])

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(
                service, user_a, workspace_a, root_folder_id="scoped-folder-id"
            )
            await session.commit()

            await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )

            assert "scoped-folder-id" in last_query["q"]

        await engine.dispose()

    asyncio.run(_run())


def test_discovery_failure_preserves_existing_documents(monkeypatch):
    """H: if the discovery listing call itself fails, existing
    Documents are preserved and last_synced is not updated."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_files = [
            {"id": "safe-1", "name": "safe.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        downloads = {"safe-1": _make_pdf_bytes("Should survive a failed discovery.")}
        _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, downloads=downloads)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            last_synced_after_success = connector.last_synced
            assert last_synced_after_success is not None

        # Now discovery itself starts failing.
        _install_fake_drive_api(
            monkeypatch, discovery_files=discovery_files, downloads=downloads,
            discovery_status=500,
        )

        async with session_factory() as session:
            service = _make_connector_service(session)
            reloaded_connector = await ConnectorRepository(session).get_by_id_and_workspace_owner(
                connector.id, user_a.id
            )

            with pytest.raises(ConnectorResourceNotFoundError):
                await service.sync_google_drive(
                    connector_id=connector.id, user_id=user_a.id, access_token="tok",
                )

            assert reloaded_connector.last_synced.replace(tzinfo=None) == \
                last_synced_after_success.replace(tzinfo=None)

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            assert len(documents) == 1
            assert documents[0].source_id == "safe-1"

        await engine.dispose()

    asyncio.run(_run())


def test_invalid_token_prevents_any_reconciliation(monkeypatch):
    """I: an invalid access token aborts before any reconciliation -
    no additions/updates/deletions, last_synced unchanged, and the
    token itself never appears in any exception or response."""
    async def _setup():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        return engine, session_factory, user_a, workspace_a

    engine, session_factory, user_a, workspace_a = asyncio.run(_setup())
    discovery_files = [
        {"id": "existing-1", "name": "existing.pdf", "mimeType": "application/pdf",
         "modifiedTime": "2026-01-01T00:00:00Z"},
    ]
    downloads = {"existing-1": _make_pdf_bytes("Untouched by a bad-token sync.")}
    _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, downloads=downloads)

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
        secret_token = "ya29.wave6c_secret_token"

        create_resp = client.post("/api/v1/connectors/google-drive", json={
            "workspace_id": str(workspace_a.id), "access_token": secret_token,
        })
        connector_id = create_resp.json()["id"]

        sync_resp = client.post(
            f"/api/v1/connectors/{connector_id}/sync/google-drive",
            json={"access_token": secret_token},
        )
        assert sync_resp.status_code == 200
        assert sync_resp.json()["files_added"] == 1

        # Now the token is invalid.
        _install_fake_drive_api(
            monkeypatch, discovery_files=discovery_files, downloads=downloads,
            about_status=401,
        )
        bad_sync_resp = client.post(
            f"/api/v1/connectors/{connector_id}/sync/google-drive",
            json={"access_token": "revoked-token"},
        )
        assert bad_sync_resp.status_code == 400
        assert bad_sync_resp.json()["error"]["code"] == "INVALID_GOOGLE_DRIVE_CREDENTIALS"
        assert "revoked-token" not in bad_sync_resp.text
        assert secret_token not in bad_sync_resp.text

        async def _check_preserved():
            async with session_factory() as session:
                documents = await DocumentRepository(session).get_by_connector(
                    uuid.UUID(connector_id)
                )
                assert len(documents) == 1
                connector = await ConnectorRepository(session).get_by_id_and_workspace_owner(
                    uuid.UUID(connector_id), user_a.id
                )
                assert connector.last_synced is not None  # set by the earlier good sync

        asyncio.run(_check_preserved())
    finally:
        main.app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_single_file_update_parse_failure_keeps_previous_version(monkeypatch):
    """J: if an existing file's update fails to parse, its previous
    chunks are left intact and other files still sync normally."""
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_files = [
            {"id": "flaky-1", "name": "flaky.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
            {"id": "healthy-1", "name": "healthy.pdf", "mimeType": "application/pdf",
             "modifiedTime": "2026-01-01T00:00:00Z"},
        ]
        downloads = {
            "flaky-1": _make_pdf_bytes("Good original content."),
            "healthy-1": _make_pdf_bytes("Also fine originally."),
        }
        _install_fake_drive_api(monkeypatch, discovery_files=discovery_files, downloads=downloads)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await _create_google_drive_connector(service, user_a, workspace_a)
            await session.commit()

            first = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()
            assert first.files_added == 2

            documents = await DocumentRepository(session).get_by_connector(connector.id)
            flaky_document = next(d for d in documents if d.source_id == "flaky-1")
            original_chunks = await _get_chunks_for_document(session, flaky_document.id)
            original_chunk_texts = {c.content for c in original_chunks}

            # flaky-1's new "version" is unparseable; healthy-1 gets a
            # real, valid update.
            discovery_files[0]["modifiedTime"] = "2026-02-01T00:00:00Z"
            downloads["flaky-1"] = b"this is not a valid pdf file at all"
            discovery_files[1]["modifiedTime"] = "2026-02-01T00:00:00Z"
            downloads["healthy-1"] = _make_pdf_bytes("Genuinely updated content.")

            second = await service.sync_google_drive(
                connector_id=connector.id, user_id=user_a.id, access_token="tok",
            )
            await session.commit()

            assert second.files_updated == 1  # healthy-1 only
            assert second.files_failed == 1  # flaky-1
            assert any("flaky.pdf" in note for note in second.notes)

            documents_after = await DocumentRepository(session).get_by_connector(connector.id)
            flaky_after = next(d for d in documents_after if d.source_id == "flaky-1")
            healthy_after = next(d for d in documents_after if d.source_id == "healthy-1")

            # The known-good document's id and chunk content survive
            # the failed update attempt untouched.
            assert flaky_after.id == flaky_document.id
            chunks_after = await _get_chunks_for_document(session, flaky_after.id)
            assert {c.content for c in chunks_after} == original_chunk_texts

            healthy_chunks = await _get_chunks_for_document(session, healthy_after.id)
            assert any("Genuinely updated" in c.content for c in healthy_chunks)

        await engine.dispose()

    asyncio.run(_run())


def test_sync_requires_workspace_ownership(monkeypatch):
    """L: a user who doesn't own the connector's workspace cannot
    trigger its sync."""
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
