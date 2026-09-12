"""Wave 5C-specific tests: incremental GitHub sync.

Covers what's new in this wave beyond basic sync (already covered in
test_connector_sync_wave5b.py): unchanged files aren't refetched/
reindexed, a changed blob SHA triggers a refetch+reindex in place,
files removed from the repository have their Document (and chunks/
local file/Qdrant vectors) removed, connector-scoped isolation (one
connector can never touch another connector's, or a manual upload's,
documents), and a connector with no stored repository refuses to sync.

Same fakes/mocks as test_connector_sync_wave5b.py: GitHub API calls
monkeypatched, embeddings faked, Qdrant faked, document storage
redirected to a temp directory - no real network, GitHub token,
Qdrant, or embedding model used anywhere.
"""

import asyncio
import base64
import shutil
import tempfile
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.connector  # noqa: F401
import app.models.document  # noqa: F401
import app.models.user  # noqa: F401
import app.models.workspace  # noqa: F401
from app.connectors import github_connector as github_connector_module
from app.database.base import Base
from app.models.chunk import Chunk
from app.models.connector import Connector
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services import document_service as document_service_module
from app.services.connector_service import ConnectorMissingRepositoryError, ConnectorService
from app.services.document_service import DocumentService


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


_README_V1 = _b64(
    "# Project Guide\n\nThis repository documents a sample project, "
    "version one of the readme, with enough text to be chunked."
)
_README_V2 = _b64(
    "# Project Guide (updated)\n\nThis is the SECOND version of the "
    "readme, with different content so re-indexing is observable."
)
_GUIDE_TEXT = _b64(
    "This is the plain text guide file, with enough content to be "
    "chunked meaningfully by the existing text parser."
)


class GitHubServer:
    """A tiny mutable fake GitHub backend: change `.tree`/`.blobs`
    between sync calls to simulate new/changed/deleted files across
    successive syncs of the same repository.
    """

    def __init__(self):
        self.tree = {
            "tree": [
                {"path": "README.md", "type": "blob", "sha": "sha-readme-v1", "size": 200},
                {"path": "docs/guide.txt", "type": "blob", "sha": "sha-guide", "size": 200},
            ]
        }
        self.blobs = {
            "sha-readme-v1": {"content": _README_V1, "encoding": "base64"},
            "sha-guide": {"content": _GUIDE_TEXT, "encoding": "base64"},
        }
        self.user_status = 200
        self.repo_status = 200

    def install(self, monkeypatch):
        def fake_get(url, headers=None, timeout=None):
            if url.endswith("/user"):
                return _FakeResponse(self.user_status, {})
            if "/git/trees/" in url:
                return _FakeResponse(200, self.tree)
            if "/git/blobs/" in url:
                sha = url.rsplit("/", 1)[-1]
                return _FakeResponse(200, self.blobs.get(sha, {}))
            return _FakeResponse(
                self.repo_status,
                {"full_name": "octocat/Hello-World", "private": False, "default_branch": "main"},
            )

        monkeypatch.setattr(github_connector_module.requests, "get", fake_get)


class FakeVectorStore:
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
    temp_dir = tempfile.mkdtemp(prefix="lumora-test-storage-5c-")
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
        workspace_a = Workspace(id=uuid4(), user_id=user_a.id, name="WS-A")
        connector = Connector(
            id=uuid4(), workspace_id=workspace_a.id, type="github",
            connection_name="octocat/Hello-World", github_repo="octocat/Hello-World",
            active=True,
        )
        session.add_all([user_a, workspace_a, connector])
        await session.commit()
        return user_a, workspace_a, connector


def _make_connector_service(session, vector_store):
    document_service = DocumentService(
        DocumentRepository(session), WorkspaceRepository(session),
        ChunkRepository(session), vector_store,
    )
    return ConnectorService(
        ConnectorRepository(session), WorkspaceRepository(session), document_service
    )


def test_unchanged_file_is_not_refetched_or_reindexed(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, workspace_a, connector = await _seed(session_factory)
        server = GitHubServer()
        server.install(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            await service.sync_github(connector_id=connector.id, user_id=user_a.id, github_token="tok")
            await session.commit()

            document_repo = DocumentRepository(session)
            readme_before = await document_repo.get_by_workspace_and_filename(workspace_a.id, "README.md")
            uploaded_at_before = readme_before.uploaded_at
            chunk_count_before = readme_before.chunk_count

        # second sync: nothing on the fake GitHub server changed at all
        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary = await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="tok"
            )
            await session.commit()

            assert summary.files_unchanged == 2
            assert summary.files_added == 0
            assert summary.files_updated == 0
            assert summary.files_deleted == 0

            document_repo = DocumentRepository(session)
            readme_after = await document_repo.get_by_workspace_and_filename(workspace_a.id, "README.md")
            # same Document row (not recreated), same chunk count, and its
            # uploaded_at timestamp is untouched since it was never rewritten
            assert readme_after.id == readme_before.id
            assert readme_after.uploaded_at == uploaded_at_before
            assert readme_after.chunk_count == chunk_count_before

        await engine.dispose()

    asyncio.run(_run())


def test_changed_sha_causes_refetch_and_reindex(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, workspace_a, connector = await _seed(session_factory)
        server = GitHubServer()
        server.install(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            await service.sync_github(connector_id=connector.id, user_id=user_a.id, github_token="tok")
            await session.commit()

            document_repo = DocumentRepository(session)
            readme_before = await document_repo.get_by_workspace_and_filename(workspace_a.id, "README.md")
            document_id = readme_before.id

        # README.md changes: new sha, new content; guide.txt is untouched
        server.tree["tree"][0]["sha"] = "sha-readme-v2"
        server.blobs["sha-readme-v2"] = {"content": _README_V2, "encoding": "base64"}

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary = await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="tok"
            )
            await session.commit()

            assert summary.files_updated == 1
            assert summary.files_unchanged == 1
            assert summary.files_added == 0
            assert summary.files_deleted == 0

            document_repo = DocumentRepository(session)
            readme_after = await document_repo.get_by_workspace_and_filename(workspace_a.id, "README.md")
            # same logical document identity preserved, not a new Document
            assert readme_after.id == document_id

            rows = await session.execute(select(Chunk).where(Chunk.document_id == document_id))
            chunks = rows.scalars().all()
            assert len(chunks) > 0
            # chunks were replaced, not appended to (chunk_count matches
            # what's actually in the DB, and content reflects the new text)
            assert len(chunks) == readme_after.chunk_count
            assert any("updated" in chunk.content.lower() for chunk in chunks)
            assert all(chunk.metadata_["github_sha"] == "sha-readme-v2" for chunk in chunks)

        await engine.dispose()

    asyncio.run(_run())


def test_deleted_github_file_removes_document_chunks_and_vectors(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, workspace_a, connector = await _seed(session_factory)
        server = GitHubServer()
        server.install(monkeypatch)

        vector_store = FakeVectorStore()

        async with session_factory() as session:
            service = _make_connector_service(session, vector_store)
            await service.sync_github(connector_id=connector.id, user_id=user_a.id, github_token="tok")
            await session.commit()

            document_repo = DocumentRepository(session)
            guide_before = await document_repo.get_by_workspace_and_filename(
                workspace_a.id, "docs/guide.txt"
            )
            guide_document_id = guide_before.id
            assert guide_before is not None

        # docs/guide.txt is removed from the repository entirely
        server.tree["tree"] = [
            entry for entry in server.tree["tree"] if entry["path"] != "docs/guide.txt"
        ]

        async with session_factory() as session:
            service = _make_connector_service(session, vector_store)
            summary = await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="tok"
            )
            await session.commit()

            assert summary.files_deleted == 1
            assert summary.files_unchanged == 1  # README.md is still there, untouched

            document_repo = DocumentRepository(session)
            # the Document row is gone
            gone = await document_repo.get_by_workspace_and_filename(workspace_a.id, "docs/guide.txt")
            assert gone is None

            # its chunks are gone (cascade)
            rows = await session.execute(select(Chunk).where(Chunk.document_id == guide_document_id))
            assert rows.scalars().all() == []

            # and its Qdrant vectors were explicitly cleaned up
            assert guide_document_id in vector_store.deleted_document_ids

            # README.md is completely unaffected
            readme = await document_repo.get_by_workspace_and_filename(workspace_a.id, "README.md")
            assert readme is not None

        await engine.dispose()

    asyncio.run(_run())


def test_connector_a_cannot_affect_connector_bs_documents(monkeypatch):
    """Two GitHub connectors in the same workspace, syncing different
    repositories - syncing connector A must never touch connector B's
    documents, even though both belong to the same workspace.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, workspace_a, connector_a = await _seed(session_factory)

        async with session_factory() as session:
            connector_b = Connector(
                id=uuid4(), workspace_id=workspace_a.id, type="github",
                connection_name="octocat/Spoon-Knife", github_repo="octocat/Spoon-Knife",
                active=True,
            )
            session.add(connector_b)
            await session.commit()
            connector_b_id = connector_b.id

        def fake_get_factory(repo_tree, full_name):
            def fake_get(url, headers=None, timeout=None):
                if url.endswith("/user"):
                    return _FakeResponse(200, {})
                if "/git/trees/" in url:
                    return _FakeResponse(200, repo_tree)
                if "/git/blobs/" in url:
                    sha = url.rsplit("/", 1)[-1]
                    if sha == "shared-path-sha":
                        return _FakeResponse(200, {"content": _GUIDE_TEXT, "encoding": "base64"})
                    return _FakeResponse(200, {})
                return _FakeResponse(200, {"full_name": full_name, "private": False, "default_branch": "main"})
            return fake_get

        # Both repositories happen to have a file at the same path -
        # this must still result in two independent Documents, one per
        # connector, never one overwriting or deleting the other's.
        shared_path_tree = {"tree": [{"path": "shared.txt", "type": "blob", "sha": "shared-path-sha", "size": 50}]}

        monkeypatch.setattr(
            github_connector_module.requests, "get",
            fake_get_factory(shared_path_tree, "octocat/Hello-World"),
        )
        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary_a = await service.sync_github(
                connector_id=connector_a.id, user_id=user_a.id, github_token="tok-a"
            )
            await session.commit()
        assert summary_a.files_added == 1

        monkeypatch.setattr(
            github_connector_module.requests, "get",
            fake_get_factory(shared_path_tree, "octocat/Spoon-Knife"),
        )
        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary_b = await service.sync_github(
                connector_id=connector_b_id, user_id=user_a.id, github_token="tok-b"
            )
            await session.commit()
        assert summary_b.files_added == 1

        async with session_factory() as session:
            docs_a = await DocumentRepository(session).get_by_connector(connector_a.id)
            docs_b = await DocumentRepository(session).get_by_connector(connector_b_id)
            assert len(docs_a) == 1
            assert len(docs_b) == 1
            assert docs_a[0].id != docs_b[0].id
            assert docs_a[0].connector_id == connector_a.id
            assert docs_b[0].connector_id == connector_b_id

        # now delete the file from connector A's repo - only connector A's
        # document should disappear; connector B's must be untouched
        monkeypatch.setattr(
            github_connector_module.requests, "get",
            fake_get_factory({"tree": []}, "octocat/Hello-World"),
        )
        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary_a2 = await service.sync_github(
                connector_id=connector_a.id, user_id=user_a.id, github_token="tok-a"
            )
            await session.commit()
        assert summary_a2.files_deleted == 1

        async with session_factory() as session:
            docs_a = await DocumentRepository(session).get_by_connector(connector_a.id)
            docs_b = await DocumentRepository(session).get_by_connector(connector_b_id)
            assert docs_a == []
            assert len(docs_b) == 1  # untouched

        await engine.dispose()

    asyncio.run(_run())


def test_connector_never_touches_manually_uploaded_documents(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, workspace_a, connector = await _seed(session_factory)
        server = GitHubServer()
        # the manual upload happens to share a path with nothing on GitHub
        server.tree = {"tree": []}
        server.install(monkeypatch)

        async with session_factory() as session:
            document_service = DocumentService(
                DocumentRepository(session), WorkspaceRepository(session),
                ChunkRepository(session), FakeVectorStore(),
            )
            manual = await document_service.upload_document(
                workspace_id=workspace_a.id, user_id=user_a.id,
                filename="manual-notes.md", content_type=None,
                content=b"# Manual notes\n\nNot from GitHub at all.",
                connector_id=None,
            )
            await session.commit()
            manual_id = manual.id

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary = await service.sync_github(
                connector_id=connector.id, user_id=user_a.id, github_token="tok"
            )
            await session.commit()

            # nothing discovered on (empty) GitHub, and nothing to delete,
            # since the manual upload isn't owned by this connector
            assert summary.files_discovered == 0
            assert summary.files_deleted == 0

            still_there = await DocumentRepository(session).get_by_id_and_workspace_owner(
                manual_id, user_a.id
            )
            assert still_there is not None
            assert still_there.connector_id is None

        await engine.dispose()

    asyncio.run(_run())


def test_invalid_token_does_not_update_last_synced(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _workspace_a, connector = await _seed(session_factory)
        server = GitHubServer()
        server.user_status = 401
        server.install(monkeypatch)

        from app.connectors.base import ConnectorAuthenticationError

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            with pytest.raises(ConnectorAuthenticationError):
                await service.sync_github(
                    connector_id=connector.id, user_id=user_a.id, github_token="bad"
                )

            refreshed = await ConnectorRepository(session).get_by_id_and_workspace_owner(
                connector.id, user_a.id
            )
            assert refreshed.last_synced is None

        await engine.dispose()

    asyncio.run(_run())


def test_connector_missing_repository_is_rejected(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()

        async with session_factory() as session:
            user_a = User(id=uuid4(), email="a@example.com", name="A")
            workspace_a = Workspace(id=uuid4(), user_id=user_a.id, name="WS-A")
            # simulates a connector created before Wave 5C's migration:
            # github_repo is NULL
            legacy_connector = Connector(
                id=uuid4(), workspace_id=workspace_a.id, type="github",
                connection_name="My GitHub Connector", github_repo=None, active=True,
            )
            session.add_all([user_a, workspace_a, legacy_connector])
            await session.commit()
            user_id, connector_id = user_a.id, legacy_connector.id

        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            with pytest.raises(ConnectorMissingRepositoryError):
                await service.sync_github(
                    connector_id=connector_id, user_id=user_id, github_token="tok"
                )

        await engine.dispose()

    asyncio.run(_run())
