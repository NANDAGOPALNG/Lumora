"""Shared helpers for the Wave 7 integration tests.

Builds a TestClient over the real FastAPI app with an in-memory SQLite
database, *real* JWT authentication, and fakes only for the external
systems (embedding model, Qdrant, reranker model, Gemini).
"""

import asyncio
import shutil
import tempfile
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chunk  # noqa: F401
import app.models.connector  # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.document  # noqa: F401
import app.models.message  # noqa: F401
import app.models.user  # noqa: F401
import app.models.workspace  # noqa: F401
import app.services.document_service as document_service_module
import main
from app.api.v1.document.router import get_vector_store
from app.auth.token_manager import TokenManager
from app.config.settings import Settings
from app.database.base import Base
from app.database.session import get_db
from app.models.user import User
from app.models.workspace import Workspace


def fake_embed_texts(texts):
    return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    """In-memory stand-in for QdrantVectorStore, recording what DocumentService does."""

    def __init__(self):
        self.points_by_document = {}
        self.deleted_document_ids = []

    async def upsert_chunks(self, points):
        for point in points:
            self.points_by_document.setdefault(point.document_id, []).append(point)

    async def delete_document_chunks(self, document_id):
        self.points_by_document.pop(document_id, None)
        self.deleted_document_ids.append(document_id)


@pytest.fixture
def storage_and_embeddings(monkeypatch):
    """Per-test temp document storage plus a fake embedding model."""
    temp_dir = tempfile.mkdtemp(prefix="lumora-w7-")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", temp_dir)
    monkeypatch.setattr(document_service_module, "embed_texts", fake_embed_texts)
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class AppHarness:
    """A TestClient over the real app, two users with one workspace each, and a fake vector store."""

    def __init__(self):
        self.vector_store = FakeVectorStore()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(self.engine.sync_engine, "connect")
        def _fk_pragma(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.user_a, self.user_b, self.workspace_a, self.workspace_b = asyncio.run(self._seed())

        settings = Settings.get_instance()
        self.token_manager = TokenManager(
            settings.secret_key, settings.algorithm, settings.access_token_expire_minutes
        )

        async def override_get_db():
            async with self.session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        main.app.dependency_overrides[get_db] = override_get_db
        main.app.dependency_overrides[get_vector_store] = lambda: self.vector_store
        self.client = TestClient(main.app, raise_server_exceptions=False)

    async def _seed(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self.session_factory() as session:
            user_a = User(id=uuid4(), email="a@example.com", name="A")
            user_b = User(id=uuid4(), email="b@example.com", name="B")
            workspace_a = Workspace(id=uuid4(), user_id=user_a.id, name="WS-A")
            workspace_b = Workspace(id=uuid4(), user_id=user_b.id, name="WS-B")
            session.add_all([user_a, user_b, workspace_a, workspace_b])
            await session.commit()
            return user_a, user_b, workspace_a, workspace_b

    def headers(self, user):
        return {"Authorization": f"Bearer {self.token_manager.create_access_token(user.id)}"}

    def run(self, coro):
        return asyncio.run(coro)

    def close(self):
        main.app.dependency_overrides.clear()
        asyncio.run(self.engine.dispose())


@pytest.fixture
def harness(storage_and_embeddings):
    h = AppHarness()
    yield h
    h.close()
