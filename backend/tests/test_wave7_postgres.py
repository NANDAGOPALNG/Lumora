"""PostgreSQL-only behavior that the SQLite-based suite cannot exercise.

Skipped unless LUMORA_TEST_POSTGRES_URL points at a *disposable*
PostgreSQL database (all Lumora tables in it are created and then
dropped), e.g.:

    LUMORA_TEST_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/lumora_test \\
        uv run python -m pytest -q tests/test_wave7_postgres.py

Covers: the real full-text KeywordRetriever (websearch_to_tsquery /
ts_rank), foreign-key cascades and SET NULL behavior, and the
(connector_id, source_id) unique index.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chunk  # noqa: F401
import app.models.connector  # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.document  # noqa: F401
import app.models.message  # noqa: F401
import app.models.user  # noqa: F401
import app.models.workspace  # noqa: F401
from app.database.base import Base
from app.models.chunk import Chunk
from app.models.connector import Connector
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.retrieval import KeywordRetriever

POSTGRES_URL = os.environ.get("LUMORA_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="LUMORA_TEST_POSTGRES_URL is not set (PostgreSQL-only tests)"
)


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://", 1
    )


def _run(scenario):
    """Create the schema, run `scenario(session_factory)`, always drop the schema."""

    async def main():
        engine = create_async_engine(_async_url(POSTGRES_URL))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            return await scenario(factory)
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()

    return asyncio.run(main())


async def _seed(session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@example.com", name="U")
    ws1 = Workspace(id=uuid.uuid4(), user_id=user.id, name="one")
    ws2 = Workspace(id=uuid.uuid4(), user_id=user.id, name="two")
    session.add_all([user, ws1, ws2])
    await session.flush()
    return user, ws1, ws2


def _document(workspace, name, connector_id=None, source_id=None):
    return Document(
        id=uuid.uuid4(), workspace_id=workspace.id, connector_id=connector_id, source_id=source_id,
        filename=name, file_type="txt", file_size=10, storage_path=f"/tmp/{uuid.uuid4()}.txt",
        status=DocumentStatus.INDEXED, chunk_count=1,
    )


def _chunk(document, index, content):
    return Chunk(
        id=uuid.uuid4(), document_id=document.id, chunk_index=index, content=content,
        metadata_={"source": "txt"},
    )


def test_keyword_retriever_uses_real_full_text_search_and_scopes_by_workspace():
    async def scenario(factory):
        async with factory() as session:
            _user, ws1, ws2 = await _seed(session)
            doc1, doc2, other_ws_doc = (
                _document(ws1, "orchids.txt"), _document(ws1, "budget.txt"), _document(ws2, "secret.txt"),
            )
            session.add_all([doc1, doc2, other_ws_doc])
            await session.flush()
            session.add_all([
                _chunk(doc1, 0, "The zephyrine orchid blooms at midnight in Lisbon."),
                _chunk(doc1, 1, "Orchids prefer humid air and indirect light."),
                _chunk(doc2, 0, "Quarterly budget review and parking policy."),
                _chunk(other_ws_doc, 0, "Confidential zephyrine orchid formula for another workspace."),
            ])
            await session.commit()

            retriever = KeywordRetriever(session)
            hits = await retriever.search("zephyrine orchid", ws1.id, top_k=5)
            assert [h.filename for h in hits][0] == "orchids.txt"
            assert all(h.workspace_id == ws1.id for h in hits)  # never the other workspace's chunk
            assert "secret.txt" not in {h.filename for h in hits}
            assert "budget.txt" not in {h.filename for h in hits}
            assert hits[0].score > 0 and "zephyrine" in hits[0].content

            # English stemming: "blooming" matches "blooms"
            stemmed = await retriever.search("blooming", ws1.id, top_k=5)
            assert stemmed and stemmed[0].filename == "orchids.txt"

            # document_id narrows, still within the workspace
            narrowed = await retriever.search("orchid", ws1.id, document_id=doc2.id, top_k=5)
            assert narrowed == []

            # the other workspace only sees its own data
            theirs = await retriever.search("zephyrine", ws2.id, top_k=5)
            assert [h.filename for h in theirs] == ["secret.txt"]

            # punctuation/operators in user input must not break the query
            assert await retriever.search('orchid" OR (', ws1.id, top_k=5) is not None

    _run(scenario)


def test_foreign_key_cascades_and_set_null():
    async def scenario(factory):
        async with factory() as session:
            _user, ws1, _ws2 = await _seed(session)
            connector = Connector(
                id=uuid.uuid4(), workspace_id=ws1.id, type="google_drive",
                connection_name="drive", active=True,
            )
            session.add(connector)
            await session.flush()
            owned = _document(ws1, "owned.txt", connector_id=connector.id, source_id="drive-1")
            manual = _document(ws1, "manual.txt")
            session.add_all([owned, manual])
            await session.flush()
            session.add_all([_chunk(owned, 0, "owned chunk"), _chunk(manual, 0, "manual chunk")])
            await session.commit()

            # deleting a connector keeps its documents but detaches them (ON DELETE SET NULL)
            await session.delete(connector)
            await session.commit()
            detached = (await session.execute(select(Document).where(Document.id == owned.id))).scalar_one()
            await session.refresh(detached)
            assert detached.connector_id is None
            assert detached.source_id == "drive-1"

            # deleting a document cascades to its chunks
            await session.delete(manual)
            await session.commit()
            remaining = (await session.execute(select(Chunk.content))).scalars().all()
            assert remaining == ["owned chunk"]

            # deleting a workspace cascades to documents and chunks
            ws = (await session.execute(select(Workspace).where(Workspace.id == ws1.id))).scalar_one()
            await session.delete(ws)
            await session.commit()
            assert (await session.execute(text("select count(*) from documents"))).scalar_one() == 0
            assert (await session.execute(text("select count(*) from chunks"))).scalar_one() == 0

    _run(scenario)


def test_connector_and_source_id_unique_index_is_enforced():
    async def scenario(factory):
        async with factory() as session:
            _user, ws1, _ws2 = await _seed(session)
            connector = Connector(
                id=uuid.uuid4(), workspace_id=ws1.id, type="google_drive",
                connection_name="drive", active=True,
            )
            other = Connector(
                id=uuid.uuid4(), workspace_id=ws1.id, type="google_drive",
                connection_name="drive2", active=True,
            )
            session.add_all([connector, other])
            await session.flush()

            session.add(_document(ws1, "a.pdf", connector_id=connector.id, source_id="file-1"))
            # same Drive file ID under a *different* connector is fine
            session.add(_document(ws1, "a-copy.pdf", connector_id=other.id, source_id="file-1"))
            # many documents without a source_id (GitHub / manual) never collide
            for i in range(3):
                session.add(_document(ws1, f"gh-{i}.md", connector_id=connector.id))
            session.add(_document(ws1, "manual.txt"))
            await session.commit()

            # a second document for the same connector + Drive file ID is rejected by the database itself
            session.add(_document(ws1, "dup.pdf", connector_id=connector.id, source_id="file-1"))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

    _run(scenario)
