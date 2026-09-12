"""Wave 5A regression tests: connector creation, listing, and
deletion (POST /connectors/github, GET /connectors,
DELETE /connectors/{id}).

No test file for Wave 5A existed in this repository tree, so this
module re-establishes it against the current codebase (which now also
includes Wave 5B's sync_github) - it does not re-test sync, that's
covered by test_connector_sync_wave5b.py and
test_github_connector_wave5b.py.

All GitHub API calls are mocked - no real token or network access is
used or required.
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
from app.connectors import github_connector as github_connector_module
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
    ConnectorWorkspaceNotFoundError,
)
from app.services.document_service import DocumentService


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _mock_github_get(monkeypatch, *, user_status=200, repo_status=200, repo_json=None):
    repo_json = repo_json or {
        "full_name": "octocat/Hello-World", "private": False, "default_branch": "main",
    }

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/user"):
            return _FakeResponse(user_status, {})
        return _FakeResponse(repo_status, repo_json)

    monkeypatch.setattr(github_connector_module.requests, "get", fake_get)


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


def test_valid_credentials_and_repository_create_and_persist_connector(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_github_get(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session)
            connector = await service.connect_github(
                user_id=user_a.id, workspace_id=workspace_a.id,
                repo_full_name="octocat/Hello-World", github_token="ghp_validtoken",
            )
            await session.commit()

            assert connector.type == "github"
            assert connector.connection_name == "octocat/Hello-World"
            assert connector.github_repo == "octocat/Hello-World"
            assert connector.active is True

            fetched = await ConnectorRepository(session).get_by_id_and_workspace_owner(
                connector.id, user_a.id
            )
            assert fetched is not None

        await engine.dispose()

    asyncio.run(_run())


def test_invalid_github_credentials_are_rejected(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_github_get(monkeypatch, user_status=401)

        async with session_factory() as session:
            service = _make_connector_service(session)
            with pytest.raises(ConnectorAuthenticationError):
                await service.connect_github(
                    user_id=user_a.id, workspace_id=workspace_a.id,
                    repo_full_name="octocat/Hello-World", github_token="bad-token",
                )

            connectors = await ConnectorRepository(session).get_by_workspace_owner(
                workspace_a.id, user_a.id
            )
            assert connectors == []

        await engine.dispose()

    asyncio.run(_run())


def test_inaccessible_repository_is_rejected(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, _user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_github_get(monkeypatch, user_status=200, repo_status=404)

        async with session_factory() as session:
            service = _make_connector_service(session)
            with pytest.raises(ConnectorResourceNotFoundError):
                await service.connect_github(
                    user_id=user_a.id, workspace_id=workspace_a.id,
                    repo_full_name="octocat/does-not-exist", github_token="ghp_validtoken",
                )

            connectors = await ConnectorRepository(session).get_by_workspace_owner(
                workspace_a.id, user_a.id
            )
            assert connectors == []

        await engine.dispose()

    asyncio.run(_run())


def test_connector_listing_is_workspace_scoped_and_cross_user_denied(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, user_b, workspace_a, workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        _mock_github_get(monkeypatch)

        async with session_factory() as session:
            service = _make_connector_service(session)

            conn_a = await service.connect_github(
                user_id=user_a.id, workspace_id=workspace_a.id,
                repo_full_name="octocat/Hello-World", github_token="tok-a",
            )
            conn_b = await service.connect_github(
                user_id=user_b.id, workspace_id=workspace_b.id,
                repo_full_name="octocat/Spoon-Knife", github_token="tok-b",
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


def test_router_end_to_end_and_credentials_never_leak(monkeypatch):
    async def _setup():
        engine, session_factory = await _make_engine_and_session_factory()
        user_a, user_b, workspace_a, _workspace_b = await _seed_two_users_with_workspaces(
            session_factory
        )
        return engine, session_factory, user_a, user_b, workspace_a

    engine, session_factory, user_a, user_b, workspace_a = asyncio.run(_setup())
    _mock_github_get(monkeypatch)

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
        secret_token = "ghp_super_secret_value_12345"

        create_resp = client.post("/api/v1/connectors/github", json={
            "workspace_id": str(workspace_a.id),
            "repo_full_name": "octocat/Hello-World",
            "github_token": secret_token,
        })
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert set(body.keys()) == {
            "id", "workspace_id", "type", "connection_name", "github_repo",
            "last_synced", "active",
        }
        assert body["github_repo"] == "octocat/Hello-World"
        assert secret_token not in create_resp.text
        connector_id = body["id"]

        bad_workspace_resp = client.post("/api/v1/connectors/github", json={
            "workspace_id": str(uuid4()),
            "repo_full_name": "octocat/Hello-World",
            "github_token": secret_token,
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
        assert delete_resp.content == b""

        list_after_resp = client.get(f"/api/v1/connectors?workspace_id={workspace_a.id}")
        assert list_after_resp.json() == []
    finally:
        main.app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
