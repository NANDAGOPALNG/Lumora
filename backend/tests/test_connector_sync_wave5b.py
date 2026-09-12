"""Focused tests for the core sync orchestration introduced in Wave 5B
and carried forward (with an updated signature/response shape) into
Wave 5C: ConnectorService.sync_github and
POST /api/v1/connectors/{id}/sync.

Wave 5C-specific behavior (incremental new/changed/unchanged/deleted
file handling, connector-scoped ownership, missing-repository
handling) is covered separately in test_connector_sync_wave5c.py -
this file focuses on the pipeline-integration, metadata-preservation,
ownership, and token-safety properties that predate Wave 5C and still
apply to it.

Uses an in-memory SQLite database (PRAGMA foreign_keys=ON, matching
PostgreSQL's FK enforcement) with the real User/Workspace/Connector/
Document/Chunk models and the real DocumentService/ConnectorService/
repositories - so this exercises the actual ingestion pipeline
(parsing, chunking, chunk persistence) for real. Only the genuinely
expensive/external pieces are faked:

- GitHub API calls: monkeypatched (see test_github_connector_wave5b.py
  for the connector-level equivalent) - no real token or network call.
- Embeddings: `app.services.document_service.embed_texts` is
  monkeypatched to return fixed-size fake vectors instantly, instead
  of loading the real BGE-M3 model.
- Qdrant: a FakeVectorStore stands in for QdrantVectorStore - no real
  Qdrant connection is made or required.

Document storage is redirected to a temporary directory for the
duration of these tests (via the DOCUMENT_STORAGE_PATH env var), so
nothing is written under the repository's real storage/ directory.
"""

import asyncio
import base64
import shutil
import tempfile
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.connector  # noqa: F401 - registers ORM models on Base
import app.models.document  # noqa: F401
import app.models.user  # noqa: F401
import app.models.workspace  # noqa: F401
import main
from app.api.v1.connectors.router import get_connector_service
from app.auth.dependencies import get_current_user
from app.connectors import github_connector as github_connector_module
from app.database.base import Base
from app.database.session import get_db
from app.models.chunk import Chunk
from app.models.connector import Connector
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services import document_service as document_service_module
from app.services.connector_service import (
    ConnectorNotFoundError,
    ConnectorService,
    ConnectorTypeMismatchError,
)
from app.services.document_service import DocumentService


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


_SAMPLE_TREE = {
    "tree": [
        {"path": "README.md", "type": "blob", "sha": "sha-readme", "size": 200},
        {"path": "docs/guide.txt", "type": "blob", "sha": "sha-guide", "size": 200},
    ]
}

_BLOB_CONTENT = {
    "sha-readme": _b64(
        "# Project Guide\n\nThis repository documents a sample project. "
        "It has quite a bit of explanatory text so the parser produces "
        "at least one real chunk of content for the tests below."
    ),
    "sha-guide": _b64(
        "This is the plain text guide file used in the GitHub connector "
        "test fixtures, with enough content to be chunked meaningfully."
    ),
}


def _mock_github(monkeypatch, *, user_status=200, repo_status=200, tree=None, blobs=None):
    repo_json = {"full_name": "octocat/Hello-World", "private": False, "default_branch": "main"}
    tree = tree if tree is not None else _SAMPLE_TREE
    blobs = blobs if blobs is not None else _BLOB_CONTENT

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/user"):
            return _FakeResponse(user_status, {})
        if "/git/trees/" in url:
            return _FakeResponse(200, tree)
        if "/git/blobs/" in url:
            sha = url.rsplit("/", 1)[-1]
            return _FakeResponse(200, {"content": blobs.get(sha, ""), "encoding": "base64"})
        return _FakeResponse(repo_status, repo_json)

    monkeypatch.setattr(github_connector_module.requests, "get", fake_get)


class FakeVectorStore:
    """Stands in for QdrantVectorStore - records calls, touches no network."""

    def __init__(self):
        self.upserted = []
        self.deleted_document_ids = []

    async def upsert_chunks(self, chunks):
        self.upserted.extend(chunks)

    async def delete_document_chunks(self, document_id):
        self.deleted_document_ids.append(document_id)


def _fake_embed_texts(texts):
    return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture(autouse=True)
def _temp_storage_and_fake_embeddings(monkeypatch):
    temp_dir = tempfile.mkdtemp(prefix="lumora-test-storage-")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", temp_dir)
    monkeypatch.setattr(document_service_module, "embed_texts", _fake_embed_texts)
    yield
    shutil.rmtree(temp_dir, ignore_errors=True)


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


async def _seed(session_factory):
    async with session_factory() as session:
        user_a = User(id=uuid4(), email="a@example.com", name="A")
        user_b = User(id=uuid4(), email="b@example.com", name="B")
        workspace_a = Workspace(id=uuid4(), user_id=user_a.id, name="WS-A")
        connector = Connector(
            id=uuid4(), workspace_id=workspace_a.id, type="github",
            connection_name="octocat/Hello-World", github_repo="octocat/Hello-World",
            active=True,
        )
        session.add_all([user_a, user_b, workspace_a, connector])
        await session.commit()
        return user_a, user_b, workspace_a, connector


def _make_connector_service(session, vector_store):
    document_service = DocumentService(
        DocumentRepository(session), WorkspaceRepository(session),
        ChunkRepository(session), vector_store,
    )
    return ConnectorService(
        ConnectorRepository(session), WorkspaceRepository(session), document_service
    )


# ---------------------------------------------------------------------------
# ConnectorService.sync_github tests
# ---------------------------------------------------------------------------


def test_sync_invokes_existing_ingestion_pipeline(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, connector = await _seed(session_factory)
        _mock_github(monkeypatch)

        async with session_factory() as session:
            vector_store = FakeVectorStore()
            service = _make_connector_service(session, vector_store)

            summary = await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="ghp_secret",
            )
            await session.commit()

            assert summary.files_discovered == 2
            assert summary.files_added == 2
            assert summary.files_updated == 0
            assert summary.files_deleted == 0
            assert summary.files_unchanged == 0
            assert summary.files_skipped == 0
            assert summary.status == "completed"
            assert summary.repository == "octocat/Hello-World"

            # the existing ingestion pipeline actually ran: real Document
            # rows, in Indexed status, with real chunk counts, connected to
            # this connector, and real (fake-embedded) vectors handed to
            # the vector store.
            documents = await DocumentRepository(session).get_by_workspace_owner(
                workspace_a.id, user_a.id
            )
            assert {d.filename for d in documents} == {"README.md", "docs/guide.txt"}
            for document in documents:
                assert document.status == DocumentStatus.INDEXED
                assert document.chunk_count > 0
                assert document.connector_id == connector.id

            assert len(vector_store.upserted) > 0

            # last_synced was updated after a fully successful sync
            refreshed = await ConnectorRepository(session).get_by_id_and_workspace_owner(
                connector.id, user_a.id
            )
            assert refreshed.last_synced is not None

        await engine.dispose()

    asyncio.run(_run())


def test_github_source_metadata_is_preserved(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, connector = await _seed(session_factory)
        _mock_github(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="ghp_secret",
            )
            await session.commit()

            document = await DocumentRepository(session).get_by_workspace_and_filename(
                workspace_a.id, "README.md"
            )
            assert document is not None
            assert document.connector_id == connector.id

            rows = await session.execute(
                select(Chunk).where(Chunk.document_id == document.id)
            )
            chunks = rows.scalars().all()
            assert len(chunks) > 0
            for chunk in chunks:
                metadata = chunk.metadata_
                assert metadata["origin"] == "github"
                assert metadata["connector_id"] == str(connector.id)
                assert metadata["repository"] == "octocat/Hello-World"
                assert metadata["branch"] == "main"
                assert metadata["path"] == "README.md"
                assert metadata["github_url"] == (
                    "https://github.com/octocat/Hello-World/blob/main/README.md"
                )
                assert metadata["github_sha"] == "sha-readme"
                # workspace_id/filename are already preserved by the
                # existing (unmodified) metadata fields
                assert metadata["workspace_id"] == str(workspace_a.id)
                assert metadata["filename"] == "README.md"

        await engine.dispose()

    asyncio.run(_run())


def test_connector_ownership_is_enforced(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        _user_a, user_b, _workspace_a, connector = await _seed(session_factory)
        _mock_github(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())

            with pytest.raises(ConnectorNotFoundError):
                await service.sync_github(
                    connector_id=connector.id, user_id=user_b.id, github_token="ghp_secret",
                )

            # nothing was ingested
            documents = await DocumentRepository(session).get_by_workspace(
                connector.workspace_id
            )
            assert documents == []

            # and last_synced was never touched
            unchanged = await ConnectorRepository(session).get_by_id_and_workspace_owner(
                connector.id, _user_a.id
            )
            assert unchanged.last_synced is None

        await engine.dispose()

    asyncio.run(_run())


def test_workspace_ownership_is_enforced_via_connector(monkeypatch):
    """A connector_id from workspace A can't be synced by a user who owns a
    *different* workspace either - ownership is enforced on the actual
    connector's workspace, not just "some workspace belonging to the user".
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        _user_a, user_b, _workspace_a, connector = await _seed(session_factory)

        async with session_factory() as session:
            # give user_b a workspace of their own, unrelated to `connector`
            other_workspace = Workspace(id=uuid4(), user_id=user_b.id, name="WS-B")
            session.add(other_workspace)
            await session.commit()

            service = _make_connector_service(session, FakeVectorStore())
            with pytest.raises(ConnectorNotFoundError):
                await service.sync_github(
                    connector_id=connector.id, user_id=user_b.id, github_token="ghp_secret",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_connector_type_mismatch_is_rejected(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _connector = await _seed(session_factory)

        async with session_factory() as session:
            non_github_connector = Connector(
                id=uuid4(), workspace_id=workspace_a.id, type="google_drive",
                connection_name="My Drive", active=True,
            )
            session.add(non_github_connector)
            await session.commit()

            service = _make_connector_service(session, FakeVectorStore())
            with pytest.raises(ConnectorTypeMismatchError):
                await service.sync_github(
                    connector_id=non_github_connector.id, user_id=user_a.id,
                    github_token="ghp_secret",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_repeated_sync_does_not_create_duplicate_documents(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, connector = await _seed(session_factory)
        _mock_github(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())

            first = await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="ghp_secret",
            )
            await session.commit()

            second = await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="ghp_secret",
            )
            await session.commit()

            assert first.files_added == 2
            # nothing changed between the two syncs, so the second sync
            # should find everything unchanged, not re-add or re-update it
            assert second.files_added == 0
            assert second.files_updated == 0
            assert second.files_unchanged == 2

            documents = await DocumentRepository(session).get_by_workspace_owner(
                workspace_a.id, user_a.id
            )
            # still exactly one Document per distinct file, not two
            assert len(documents) == 2
            assert sorted(d.filename for d in documents) == ["README.md", "docs/guide.txt"]

            # each document's chunks were replaced, not appended to
            for document in documents:
                rows = await session.execute(
                    select(Chunk).where(Chunk.document_id == document.id)
                )
                chunk_count_in_db = len(rows.scalars().all())
                assert chunk_count_in_db == document.chunk_count

        await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Router-level test: real FastAPI app + TestClient
# ---------------------------------------------------------------------------


def test_router_sync_endpoint_and_token_never_leaks(monkeypatch):
    async def _setup():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, user_b, workspace_a, connector = await _seed(session_factory)
        return engine, session_factory, user_a, user_b, workspace_a, connector

    engine, session_factory, user_a, user_b, workspace_a, connector = asyncio.run(_setup())
    _mock_github(monkeypatch)

    current_user_holder = {"user": user_a}

    async def override_get_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    async def override_get_current_user():
        return current_user_holder["user"]

    async def override_get_connector_service():
        async with session_factory() as session:
            yield _make_connector_service(session, FakeVectorStore())
            await session.commit()

    main.app.dependency_overrides[get_db] = override_get_db
    main.app.dependency_overrides[get_current_user] = override_get_current_user
    main.app.dependency_overrides[get_connector_service] = override_get_connector_service

    try:
        client = TestClient(main.app)
        secret_token = "ghp_super_secret_value_12345"

        # Wave 5C: the request no longer accepts repo_full_name at all -
        # only the credential.
        resp = client.post(f"/api/v1/connectors/{connector.id}/sync", json={
            "github_token": secret_token,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "connector_id", "repository", "files_discovered", "files_added",
            "files_updated", "files_deleted", "files_unchanged", "files_skipped",
            "status",
        }
        assert body["connector_id"] == str(connector.id)
        assert body["repository"] == "octocat/Hello-World"
        assert body["files_discovered"] == 2
        assert body["files_added"] == 2
        assert body["files_skipped"] == 0
        assert body["status"] == "completed"
        # the token never appears anywhere in the response
        assert secret_token not in resp.text
        assert "github_token" not in resp.text

        # a client can no longer smuggle a different repository into the
        # sync request - repo_full_name is not even part of the schema
        # anymore, so FastAPI/Pydantic simply ignores an extra field like
        # this rather than erroring, but it has zero effect either way.
        smuggle_resp = client.post(f"/api/v1/connectors/{connector.id}/sync", json={
            "github_token": secret_token,
            "repo_full_name": "someone-else/other-repo",
        })
        assert smuggle_resp.status_code == 200
        assert smuggle_resp.json()["repository"] == "octocat/Hello-World"

        # another user cannot sync this connector
        current_user_holder["user"] = user_b
        cross_resp = client.post(f"/api/v1/connectors/{connector.id}/sync", json={
            "github_token": secret_token,
        })
        assert cross_resp.status_code == 404
        assert cross_resp.json()["error"]["code"] == "CONNECTOR_NOT_FOUND"
        assert secret_token not in cross_resp.text
    finally:
        main.app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
