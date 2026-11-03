"""Regression tests for the production-readiness audit.

R1  vector-only search hits must reach the LLM context (and stale/foreign
    vectors must never be surfaced)
R2  model inference must not block the event loop
R3  concurrent reindexing of one document stays consistent (PostgreSQL only)
R4  a failed re-index must leave the previous chunks and vectors intact
R5  a failed end-of-request COMMIT must not be reported as success
"""

import asyncio
import os
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.retrieval.dense_retriever as dense_module
import app.retrieval.reranker as reranker_module
import app.services.document_service as document_service_module
import main
from app.database import session as session_module
from app.database.base import Base
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.retrieval import ContextBuilder, DenseRetriever, HybridRetriever, KeywordRetriever, QueryRewriter
from app.retrieval.reranker import CrossEncoderReranker
from app.services.document_service import DocumentService
from app.services.search_service import SearchService
from tests._support import FakeVectorStore, fake_embed_texts


# --------------------------------------------------------------------------- helpers

class _NoKeywordHits(KeywordRetriever):
    """PostgreSQL full-text search can't run on SQLite, so keyword *search* is
    stubbed to find nothing - while `load_contents` stays the real SQL."""

    async def search(self, *args, **kwargs):
        return []


class _LengthScoringModel:
    def predict(self, pairs):
        return [float(len(text)) for _, text in pairs]


def _point(chunk_id, document_id, workspace_id, filename="doc.txt"):
    return SimpleNamespace(
        score=0.9,
        payload={
            "chunk_id": str(chunk_id), "document_id": str(document_id),
            "workspace_id": str(workspace_id), "filename": filename,
            "chunk_index": 0, "source": "txt",
        },
    )


class _StoreReturning:
    def __init__(self, points):
        self._points = points

    async def search(self, **kwargs):
        return self._points


def _seed_chunk(harness, workspace, filename, text):
    """Insert an indexed document with one chunk straight into the database."""

    async def run():
        async with harness.session_factory() as session:
            document = Document(
                id=uuid.uuid4(), workspace_id=workspace.id, filename=filename, file_type="txt",
                file_size=len(text), storage_path=f"/nonexistent/{uuid.uuid4()}.txt",
                status=DocumentStatus.INDEXED, chunk_count=1,
            )
            session.add(document)
            await session.flush()
            chunk = Chunk(id=uuid.uuid4(), document_id=document.id, chunk_index=0, content=text, metadata_={})
            session.add(chunk)
            await session.commit()
            return document.id, chunk.id

    return harness.run(run())


async def _max_loop_gap_during(coro, tick=0.02):
    """Run `coro` while a ticker records the longest time the event loop went unserved."""
    gaps, done = [], asyncio.Event()

    async def ticker():
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(tick)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    ticker_task = asyncio.create_task(ticker())
    await asyncio.sleep(0)  # let the ticker start
    try:
        result = await coro
    finally:
        done.set()
        await ticker_task
    return result, max(gaps)


# --------------------------------------------------------------------------- R1

def test_r1_vector_only_hits_reach_the_context_and_stale_or_foreign_ones_do_not(harness, monkeypatch):
    monkeypatch.setattr(dense_module, "embed_text", lambda q: [0.1, 0.2, 0.3])
    monkeypatch.setattr(reranker_module, "_load_model", lambda: _LengthScoringModel())

    own_text = "Employees receive 25 days of annual leave per year."
    secret_text = "Confidential: another workspace's salary table."
    own_doc, own_chunk = _seed_chunk(harness, harness.workspace_a, "hr.txt", own_text)
    foreign_doc, foreign_chunk = _seed_chunk(harness, harness.workspace_b, "secret.txt", secret_text)

    store = _StoreReturning([
        _point(own_chunk, own_doc, harness.workspace_a.id, "hr.txt"),
        _point(foreign_chunk, foreign_doc, harness.workspace_a.id, "secret.txt"),  # poisoned/stale payload
        _point(uuid.uuid4(), uuid.uuid4(), harness.workspace_a.id, "ghost.txt"),   # chunk no longer exists
    ])

    async def run():
        async with harness.session_factory() as session:
            service = SearchService(
                QueryRewriter(),
                HybridRetriever(DenseRetriever(store), _NoKeywordHits(session)),
                CrossEncoderReranker(),
                ContextBuilder(),
            )
            return await service.search("How many days of annual leave do staff get?", harness.workspace_a.id)

    result = harness.run(run())

    assert own_text in result.context.text  # the LLM gets the semantically retrieved text
    assert secret_text not in result.context.text  # never another workspace's text
    assert [(s.filename, s.content) for s in result.context.sources] == [("hr.txt", own_text)]
    assert "ghost.txt" not in str(result.context.sources)  # no phantom citations


def test_r1_load_contents_is_scoped_to_the_workspace(harness):
    _doc, own_chunk = _seed_chunk(harness, harness.workspace_a, "a.txt", "alpha text")
    _doc2, other_chunk = _seed_chunk(harness, harness.workspace_b, "b.txt", "beta text")

    async def run():
        async with harness.session_factory() as session:
            retriever = KeywordRetriever(session)
            return (
                await retriever.load_contents([own_chunk, other_chunk, uuid.uuid4()], harness.workspace_a.id),
                await retriever.load_contents([], harness.workspace_a.id),
            )

    loaded, empty = harness.run(run())
    assert loaded == {own_chunk: "alpha text"}
    assert empty == {}


# --------------------------------------------------------------------------- R2

def test_r2_reindex_does_not_block_the_event_loop(harness, monkeypatch):
    headers = harness.headers(harness.user_a)
    doc_id = harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(harness.workspace_a.id)},
        files={"file": ("a.txt", b"hello world " * 40, "text/plain")},
        headers=headers,
    ).json()["id"]

    def blocking_embed(texts):  # stands in for CPU-bound model.encode
        time.sleep(0.8)
        return fake_embed_texts(texts)

    monkeypatch.setattr(document_service_module, "embed_texts", blocking_embed)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as client:
            return await _max_loop_gap_during(client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers))

    response, max_gap = asyncio.run(scenario())
    assert response.status_code == 200
    assert max_gap < 0.4, f"event loop was unresponsive for {max_gap:.2f}s during reindex embedding"


def test_r2_search_embedding_and_reranking_do_not_block_the_event_loop(harness, monkeypatch):
    own_doc, own_chunk = _seed_chunk(harness, harness.workspace_a, "hr.txt", "Employees receive 25 days of leave.")

    def blocking_embed_text(query):
        time.sleep(0.6)
        return [0.1, 0.2, 0.3]

    class _BlockingModel:
        def predict(self, pairs):
            time.sleep(0.6)
            return [1.0 for _ in pairs]

    monkeypatch.setattr(dense_module, "embed_text", blocking_embed_text)
    monkeypatch.setattr(reranker_module, "_load_model", lambda: _BlockingModel())
    store = _StoreReturning([_point(own_chunk, own_doc, harness.workspace_a.id, "hr.txt")])

    async def scenario():
        async with harness.session_factory() as session:
            service = SearchService(
                QueryRewriter(),
                HybridRetriever(DenseRetriever(store), _NoKeywordHits(session)),
                CrossEncoderReranker(),
                ContextBuilder(),
            )
            return await _max_loop_gap_during(service.search("annual leave allowance", harness.workspace_a.id))

    result, max_gap = asyncio.run(scenario())
    assert result.context.sources
    assert max_gap < 0.35, f"event loop was unresponsive for {max_gap:.2f}s during search"


# --------------------------------------------------------------------------- R4

def test_r4_failed_reindex_keeps_previous_chunks_and_leaves_no_orphan_vectors(harness, monkeypatch):
    headers = harness.headers(harness.user_a)
    doc_id = uuid.UUID(harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(harness.workspace_a.id)},
        files={"file": ("handbook.txt", b"VERSION ONE of the handbook. Holiday allowance is 25 days.", "text/plain")},
        headers=headers,
    ).json()["id"])
    assert harness.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers).status_code == 200

    async def storage_path():
        async with harness.session_factory() as session:
            return (await session.execute(select(Document.storage_path).where(Document.id == doc_id))).scalar_one()

    with open(harness.run(storage_path()), "wb") as handle:  # the source file changes...
        handle.write(b"VERSION TWO of the handbook. Holiday allowance is 30 days.")

    def broken_embed(texts):  # ...and the embedding model then fails
        raise RuntimeError("embedding model unavailable")

    monkeypatch.setattr(document_service_module, "embed_texts", broken_embed)
    response = harness.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers)
    assert response.status_code == 422

    async def state():
        async with harness.session_factory() as session:
            rows = (await session.execute(select(Chunk.id, Chunk.content).where(Chunk.document_id == doc_id))).all()
            document = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one()
            return rows, document.status

    rows, status = harness.run(state())
    assert status == DocumentStatus.FAILED  # the failure is still reported honestly
    assert all("VERSION ONE" in content for _id, content in rows)  # previous chunks untouched
    live_vector_chunk_ids = {p.chunk_id for p in harness.vector_store.points_by_document.get(doc_id, [])}
    assert live_vector_chunk_ids <= {chunk_id for chunk_id, _c in rows}  # no vector points to deleted chunks


# --------------------------------------------------------------------------- R5

def test_r5_failed_commit_is_not_reported_as_success(monkeypatch, tmp_path):
    from app.auth.token_manager import TokenManager
    from app.config.settings import Settings
    from fastapi.testclient import TestClient

    db_file = tmp_path / "r5.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setattr(main.app, "dependency_overrides", {})
    monkeypatch.setattr(session_module, "_engine", None)
    monkeypatch.setattr(session_module, "_session_factory", None)

    async def seed():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        user_id = uuid.uuid4()
        async with AsyncSession(engine) as session:
            session.add(User(id=user_id, email="r5@example.com", name="R5"))
            await session.commit()
        await engine.dispose()
        return user_id

    async def workspace_names():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        async with AsyncSession(engine) as session:
            names = (await session.execute(select(Workspace.name))).scalars().all()
        await engine.dispose()
        return sorted(names)

    user_id = asyncio.run(seed())
    settings = Settings.get_instance()
    headers = {"Authorization": "Bearer " + TokenManager(settings.secret_key, settings.algorithm, 30).create_access_token(user_id)}
    client = TestClient(main.app, raise_server_exceptions=False)

    try:
        ok = client.post("/api/v1/workspaces", json={"name": "persisted"}, headers=headers)
        assert ok.status_code == 201  # control: the normal path still works

        real_commit = AsyncSession.commit
        failing = {"on": False}

        async def flaky_commit(self):
            if failing["on"]:
                raise RuntimeError("simulated connection loss during COMMIT")
            return await real_commit(self)

        monkeypatch.setattr(AsyncSession, "commit", flaky_commit)
        failing["on"] = True
        response = client.post("/api/v1/workspaces", json={"name": "never-stored"}, headers=headers)
        failing["on"] = False

        assert response.status_code == 500, "the client must not be told the write succeeded"
        assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert asyncio.run(workspace_names()) == ["persisted"]
    finally:
        engine = session_module._engine
        if engine is not None:
            asyncio.run(engine.dispose())


# --------------------------------------------------------------------------- R3 (PostgreSQL only)

POSTGRES_URL = os.environ.get("LUMORA_TEST_POSTGRES_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="LUMORA_TEST_POSTGRES_URL is not set (PostgreSQL-only test)")
def test_r3_concurrent_reindex_of_one_document_stays_consistent(storage_and_embeddings):
    url = POSTGRES_URL.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://", 1
    )

    async def scenario():
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        store = FakeVectorStore()
        try:
            async with factory() as session:
                user = User(id=uuid.uuid4(), email="r3@example.com", name="R3")
                workspace = Workspace(id=uuid.uuid4(), user_id=user.id, name="w")
                session.add_all([user, workspace])
                await session.commit()
                service = DocumentService(
                    DocumentRepository(session), WorkspaceRepository(session), ChunkRepository(session), vector_store=store
                )
                body = "\n\n".join(f"Paragraph {i}. " + "lorem ipsum dolor sit amet " * 60 for i in range(8))
                document = await service.upload_document(
                    workspace_id=workspace.id, user_id=user.id, filename="a.txt",
                    content_type="text/plain", content=body.encode(),
                )
                await session.commit()

            async def reindex():
                async with factory() as session:
                    service = DocumentService(
                        DocumentRepository(session), WorkspaceRepository(session), ChunkRepository(session), vector_store=store
                    )
                    return await service.reindex_document_for_user(document.id, user.id)

            await reindex()
            expected = len(store.points_by_document[document.id])
            results = await asyncio.gather(reindex(), reindex(), reindex())

            async with factory() as session:
                chunk_ids = set((await session.execute(select(Chunk.id).where(Chunk.document_id == document.id))).scalars().all())
                count = (await session.execute(select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id))).scalar_one()
            points = store.points_by_document[document.id]
            return results, count, chunk_ids, points, expected
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()

    results, count, chunk_ids, points, expected = asyncio.run(scenario())
    assert all(r.status.value == "Indexed" for r in results)
    assert count == expected  # no duplicated chunks
    assert len(points) == expected and {p.chunk_id for p in points} == chunk_ids  # vectors match rows exactly
