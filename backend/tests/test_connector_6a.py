"""Wave 6A regression tests: Google Drive connector foundation
(POST /connectors/google-drive, connector persistence, discovery).

Mirrors test_connector_5a.py's structure and conventions for the
GitHub connector. All Google Drive API calls are mocked - no real
access token or network access is used or required.
"""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.connector  # noqa: F401
import app.models.document  # noqa: F401
import app.models.user  # noqa: F401
import app.models.workspace  # noqa: F401
import main
from app.api.v1.connectors.router import get_connector_service
from app.auth.dependencies import get_current_user
from app.connectors import google_drive_connector as google_drive_connector_module
from app.connectors.base import ConnectorAuthenticationError, ConnectorResourceNotFoundError
from app.database.base import Base
from app.database.session import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.connector_service import (
    ConnectorNotFoundError,
    ConnectorService,
    ConnectorTypeMismatchError,
    ConnectorWorkspaceNotFoundError,
)
from app.services.document_service import DocumentService


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _mock_drive_get(
    monkeypatch,
    *,
    about_status=200,
    about_json=None,
    folder_status=200,
    folder_json=None,
    list_status=200,
    list_pages=None,
):
    """Patches google_drive_connector.requests.get to fake the three
    Drive endpoints this connector calls: /about, /files/{id}
    (root folder validation), and /files (discovery listing, possibly
    paginated via `list_pages`, a list of response json dicts served
    in order across successive calls).
    """
    about_json = about_json or {
        "user": {"emailAddress": "user@example.com", "displayName": "User"}
    }
    folder_json = folder_json or {
        "id": "root-folder-id", "name": "Shared", "mimeType": "application/vnd.google-apps.folder",
    }
    list_pages = list_pages if list_pages is not None else [{"files": []}]
    list_call_count = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/about"):
            return _FakeResponse(about_status, about_json)
        if "/files/" in url:
            return _FakeResponse(folder_status, folder_json)
        # GET /files (discovery listing)
        index = min(list_call_count["n"], len(list_pages) - 1)
        list_call_count["n"] += 1
        return _FakeResponse(list_status, list_pages[index])

    monkeypatch.setattr(google_drive_connector_module.requests, "get", fake_get)


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


def _make_connector_service(session):
    document_service = DocumentService(
        DocumentRepository(session), WorkspaceRepository(session),
        ChunkRepository(session), vector_store=None,
    )
    return ConnectorService(
        ConnectorRepository(session), WorkspaceRepository(session), document_service
    )


def test_valid_credentials_create_and_persist_connector(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_drive_get(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await service.connect_google_drive(
                user_id=user_a.id, workspace_id=workspace_a.id,
                access_token="valid-access-token",
            )
            await session.commit()

            assert connector.type == "google_drive"
            assert connector.connection_name == "user@example.com"
            assert connector.drive_account_email == "user@example.com"
            assert connector.drive_root_folder_id is None
            assert connector.github_repo is None
            assert connector.active is True

            fetched = await ConnectorRepository(session).get_by_id_and_workspace_owner(
                connector.id, user_a.id
            )
            assert fetched is not None

        await engine.dispose()

    asyncio.run(_run())


def test_valid_credentials_with_root_folder_are_validated_and_persisted(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_drive_get(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await service.connect_google_drive(
                user_id=user_a.id, workspace_id=workspace_a.id,
                access_token="valid-access-token", root_folder_id="root-folder-id",
                connection_name="Team Drive",
            )
            await session.commit()

            assert connector.connection_name == "Team Drive"
            assert connector.drive_root_folder_id == "root-folder-id"
            assert connector.drive_account_email == "user@example.com"

        await engine.dispose()

    asyncio.run(_run())


def test_invalid_access_token_is_rejected(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_drive_get(monkeypatch, about_status=401)

        async with session_factory() as session:
            service = _make_connector_service(session)
            with pytest.raises(ConnectorAuthenticationError):
                await service.connect_google_drive(
                    user_id=user_a.id, workspace_id=workspace_a.id,
                    access_token="bad-token",
                )

            connectors = await ConnectorRepository(session).get_by_workspace_owner(
                workspace_a.id, user_a.id
            )
            assert connectors == []

        await engine.dispose()

    asyncio.run(_run())


def test_inaccessible_root_folder_is_rejected(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_drive_get(monkeypatch, folder_status=404)

        async with session_factory() as session:
            service = _make_connector_service(session)
            with pytest.raises(ConnectorResourceNotFoundError):
                await service.connect_google_drive(
                    user_id=user_a.id, workspace_id=workspace_a.id,
                    access_token="valid-access-token", root_folder_id="missing-folder",
                )

            connectors = await ConnectorRepository(session).get_by_workspace_owner(
                workspace_a.id, user_a.id
            )
            assert connectors == []

        await engine.dispose()

    asyncio.run(_run())


def test_non_folder_root_id_is_rejected(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_drive_get(
            monkeypatch,
            folder_json={"id": "file-id", "name": "notes.txt", "mimeType": "text/plain"},
        )

        async with session_factory() as session:
            service = _make_connector_service(session)
            with pytest.raises(ConnectorResourceNotFoundError):
                await service.connect_google_drive(
                    user_id=user_a.id, workspace_id=workspace_a.id,
                    access_token="valid-access-token", root_folder_id="file-id",
                )

        await engine.dispose()

    asyncio.run(_run())


def test_connector_listing_is_workspace_scoped_and_cross_user_denied(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, user_b, workspace_a, workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_drive_get(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session)

            conn_a = await service.connect_google_drive(
                user_id=user_a.id, workspace_id=workspace_a.id, access_token="tok-a",
            )
            conn_b = await service.connect_google_drive(
                user_id=user_b.id, workspace_id=workspace_b.id, access_token="tok-b",
            )
            await session.commit()

            listing_a = await service.list_connectors_for_workspace(workspace_a.id, user_a.id)
            assert [c.id for c in listing_a] == [conn_a.id]

            with pytest.raises(ConnectorWorkspaceNotFoundError):
                await service.list_connectors_for_workspace(workspace_a.id, user_b.id)

            with pytest.raises(ConnectorNotFoundError):
                await service.get_connector(conn_a.id, user_b.id)
            with pytest.raises(ConnectorNotFoundError):
                await service.delete_connector(conn_a.id, user_b.id)

            got = await service.get_connector(conn_a.id, user_a.id)
            assert got.id == conn_a.id
            await service.delete_connector(conn_a.id, user_a.id)
            await session.commit()

            remaining = await service.list_connectors_for_workspace(workspace_a.id, user_a.id)
            assert remaining == []
            still_there = await service.list_connectors_for_workspace(workspace_b.id, user_b.id)
            assert [c.id for c in still_there] == [conn_b.id]

        await engine.dispose()

    asyncio.run(_run())


def test_discovery_is_type_scoped_and_filters_correctly(monkeypatch):
    """discover_google_drive_files rejects a mismatched connector type,
    and the returned metadata correctly flags folders, Google-native
    documents, and files DocumentService can ingest.
    """
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        discovery_page = {
            "files": [
                {
                    "id": "1", "name": "report.pdf", "mimeType": "application/pdf",
                    "size": "1024", "modifiedTime": "2026-09-01T00:00:00Z",
                    "webViewLink": "https://drive.google.com/file/d/1/view", "parents": ["root"],
                },
                {
                    "id": "2", "name": "Notes", "mimeType": "application/vnd.google-apps.folder",
                    "parents": ["root"],
                },
                {
                    "id": "3", "name": "Design Doc",
                    "mimeType": "application/vnd.google-apps.document", "parents": ["root"],
                },
                {
                    "id": "4", "name": "archive.zip", "mimeType": "application/zip",
                    "size": "2048", "parents": ["root"],
                },
            ]
        }
        _mock_drive_get(monkeypatch, list_pages=[discovery_page])

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await service.connect_google_drive(
                user_id=user_a.id, workspace_id=workspace_a.id, access_token="tok",
            )
            await session.commit()

            with pytest.raises(ConnectorTypeMismatchError):
                # A GitHub-typed connector id would be rejected the same way;
                # simulate the mismatch by pointing at this Drive connector's
                # id with its .type monkey-patched.
                connector.type = "github"
                await service.discover_google_drive_files(
                    connector.id, user_a.id, access_token="tok"
                )
            connector.type = "google_drive"

            files = await service.discover_google_drive_files(
                connector.id, user_a.id, access_token="tok"
            )

        assert len(files) == 4
        by_id = {f.file_id: f for f in files}

        pdf = by_id["1"]
        assert pdf.extension == "pdf"
        assert pdf.is_folder is False and pdf.is_google_native is False
        assert pdf.size == 1024
        assert pdf.web_view_link == "https://drive.google.com/file/d/1/view"

        folder = by_id["2"]
        assert folder.is_folder is True
        assert folder.extension is None

        native_doc = by_id["3"]
        assert native_doc.is_google_native is True
        assert native_doc.extension is None

        unsupported = by_id["4"]
        assert unsupported.is_folder is False and unsupported.is_google_native is False
        assert unsupported.extension is None

        await engine.dispose()

    asyncio.run(_run())


def test_discovery_paginates_through_all_result_pages(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        page_one = {
            "nextPageToken": "page-2",
            "files": [{"id": "1", "name": "a.txt", "mimeType": "text/plain"}],
        }
        page_two = {"files": [{"id": "2", "name": "b.txt", "mimeType": "text/plain"}]}
        _mock_drive_get(monkeypatch, list_pages=[page_one, page_two])

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await service.connect_google_drive(
                user_id=user_a.id, workspace_id=workspace_a.id, access_token="tok",
            )
            await session.commit()

            files = await service.discover_google_drive_files(
                connector.id, user_a.id, access_token="tok"
            )

        assert {f.file_id for f in files} == {"1", "2"}
        await engine.dispose()

    asyncio.run(_run())


def test_router_end_to_end_and_credentials_never_leak(monkeypatch):
    async def _setup():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        return engine, session_factory, user_a, user_b, workspace_a

    engine, session_factory, user_a, user_b, workspace_a = asyncio.run(_setup())
    _mock_drive_get(monkeypatch)

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
        secret_token = "ya29.super_secret_drive_access_token"

        create_resp = client.post("/api/v1/connectors/google-drive", json={
            "workspace_id": str(workspace_a.id),
            "access_token": secret_token,
        })
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert set(body.keys()) == {
            "id", "workspace_id", "type", "connection_name", "github_repo",
            "drive_account_email", "drive_root_folder_id", "last_synced", "active",
        }
        assert body["type"] == "google_drive"
        assert body["drive_account_email"] == "user@example.com"
        assert body["github_repo"] is None
        assert secret_token not in create_resp.text
        connector_id = body["id"]

        bad_workspace_resp = client.post("/api/v1/connectors/google-drive", json={
            "workspace_id": str(uuid4()),
            "access_token": secret_token,
        })
        assert bad_workspace_resp.status_code == 404
        assert bad_workspace_resp.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"

        list_resp = client.get(f"/api/v1/connectors?workspace_id={workspace_a.id}")
        assert list_resp.status_code == 200
        assert [c["id"] for c in list_resp.json()] == [connector_id]

        current_user_holder["user"] = user_b
        cross_delete_resp = client.delete(f"/api/v1/connectors/{connector_id}")
        assert cross_delete_resp.status_code == 404
        assert cross_delete_resp.json()["error"]["code"] == "CONNECTOR_NOT_FOUND"

        current_user_holder["user"] = user_a
        delete_resp = client.delete(f"/api/v1/connectors/{connector_id}")
        assert delete_resp.status_code == 204
    finally:
        main.app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_invalid_credentials_return_400_via_router(monkeypatch):
    async def _setup():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        return engine, session_factory, user_a, workspace_a

    engine, session_factory, user_a, workspace_a = asyncio.run(_setup())
    _mock_drive_get(monkeypatch, about_status=401)

    async def override_get_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    async def override_get_current_user():
        return user_a

    async def override_get_connector_service():
        async with session_factory() as session:
            yield _make_connector_service(session)
            await session.commit()

    main.app.dependency_overrides[get_db] = override_get_db
    main.app.dependency_overrides[get_current_user] = override_get_current_user
    main.app.dependency_overrides[get_connector_service] = override_get_connector_service

    try:
        client = TestClient(main.app)
        resp = client.post("/api/v1/connectors/google-drive", json={
            "workspace_id": str(workspace_a.id),
            "access_token": "bad-token",
        })
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_GOOGLE_DRIVE_CREDENTIALS"
        assert "bad-token" not in resp.text
    finally:
        main.app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
