"""Wave 7 cross-feature workflow tests.

Workflow A: upload -> index -> search -> RAG chat -> delete.
Workflow B: conversation lifecycle and ownership.

These drive the real FastAPI routes, services, repositories, chunker,
retrieval fusion, context builder, and prompt builder. Only the
external systems are replaced: the embedding API, Qdrant, the
reranker API, Gemini, and PostgreSQL full-text search
(which SQLite can't run - the real KeywordRetriever is exercised
separately in tests/test_wave7_postgres.py when a Postgres URL is
provided).
"""

import os
import re
import uuid

import pytest
from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import main
from app.api.v1.chat.router import get_chat_service
from app.api.v1.search.router import get_search_service
from app.database.session import get_db
from app.generation.prompt_builder import RagPromptBuilder
from app.llm.base import LLMGenerationError
from app.models.chunk import Chunk
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.message import Message
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.retrieval import ContextBuilder, HybridRetriever, QueryRewriter
from app.retrieval.keyword_retriever import KeywordSearchResult
from app.retrieval.reranker import RerankedResult
from app.services.chat_service import ChatService
from app.services.search_service import SearchService

DISTINCTIVE = "zephyrine orchid blooms only at midnight in Lisbon"
DOCUMENT_TEXT = (
    f"Field notes. The rare {DISTINCTIVE}. "
    "Unrelated filler sentence about quarterly budgets and parking policy."
)


class _EmptyDenseRetriever:
    async def search(self, query, workspace_id, *, document_id=None, top_k=10):
        return []


class _SubstringKeywordRetriever:
    """Stands in for PostgreSQL full-text search: matches chunks whose
    text contains any query word, scoped to the workspace (and
    document) exactly like the real retriever's SQL.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def search(self, query, workspace_id, *, document_id=None, top_k=10):
        words = [w.lower() for w in re.findall(r"\w+", str(query)) if len(w) > 3]
        stmt = (
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.workspace_id == uuid.UUID(str(workspace_id)))
        )
        if document_id is not None:
            stmt = stmt.where(Chunk.document_id == uuid.UUID(str(document_id)))
        rows = (await self._session.execute(stmt)).all()
        results = []
        for chunk, document in rows:
            hits = sum(1 for w in words if w in chunk.content.lower())
            if hits:
                results.append(
                    KeywordSearchResult(
                        chunk_id=chunk.id,
                        document_id=document.id,
                        workspace_id=document.workspace_id,
                        filename=document.filename,
                        chunk_index=chunk.chunk_index,
                        source=document.file_type,
                        score=float(hits),
                        content=chunk.content,
                    )
                )
        results.sort(key=lambda r: (-r.score, str(r.chunk_id)))
        return results[:top_k]


class _PassthroughReranker:
    async def rerank(self, query, candidates, *, top_k=None):
        ranked = [
            RerankedResult(
                chunk_id=c.chunk_id, document_id=c.document_id, workspace_id=c.workspace_id,
                filename=c.filename, chunk_index=c.chunk_index, source=c.source,
                score=c.score, content=c.content,
            )
            for c in candidates
        ]
        return ranked[:top_k] if top_k else ranked


class _FakeLLM:
    def __init__(self):
        self.prompts = []
        self.error = None

    async def generate(self, prompt: str) -> str:
        if self.error is not None:
            raise self.error
        self.prompts.append(prompt)
        return "It blooms at midnight [1]." if "zephyrine" in prompt else "I could not find that."


@pytest.fixture
def rag(harness):
    """Wire real SearchService/ChatService over the test database with the fakes above."""
    llm = _FakeLLM()

    def build_search(session):
        hybrid = HybridRetriever(_EmptyDenseRetriever(), _SubstringKeywordRetriever(session))
        return SearchService(QueryRewriter(), hybrid, _PassthroughReranker(), ContextBuilder())

    def override_search_service(session: AsyncSession = Depends(get_db)):
        return build_search(session)

    def override_chat_service(session: AsyncSession = Depends(get_db)):
        return ChatService(
            build_search(session), llm, RagPromptBuilder(),
            ConversationRepository(session), MessageRepository(session),
        )

    main.app.dependency_overrides[get_search_service] = override_search_service
    main.app.dependency_overrides[get_chat_service] = override_chat_service
    harness.llm = llm
    return harness


def _count(harness, model, *conditions):
    async def run():
        async with harness.session_factory() as session:
            stmt = select(func.count()).select_from(model)
            for condition in conditions:
                stmt = stmt.where(condition)
            return (await session.execute(stmt)).scalar_one()

    return harness.run(run())


def _upload(harness, user, workspace, text=DOCUMENT_TEXT, name="notes.txt"):
    return harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(workspace.id)},
        files={"file": (name, text.encode(), "text/plain")},
        headers=harness.headers(user),
    )


def test_workflow_a_upload_index_search_chat_delete(rag):
    h = rag
    a_headers = h.headers(h.user_a)

    # 1-4: upload -> record -> status
    upload = _upload(h, h.user_a, h.workspace_a)
    assert upload.status_code == 201
    document = upload.json()
    doc_id = uuid.UUID(document["id"])
    assert document["status"] == "Uploaded"
    assert document["chunk_count"] == 0
    assert document["workspace_id"] == str(h.workspace_a.id)
    assert _count(h, Document, Document.id == doc_id) == 1
    assert _count(h, Chunk, Chunk.document_id == doc_id) == 0
    assert not h.vector_store.points_by_document

    # 5: index (the client triggers this explicitly) -> chunks + vectors
    reindex = h.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=a_headers)
    assert reindex.status_code == 200
    assert reindex.json()["status"] == "Indexed"
    chunk_count = reindex.json()["chunk_count"]
    assert chunk_count >= 1
    assert _count(h, Chunk, Chunk.document_id == doc_id) == chunk_count
    points = h.vector_store.points_by_document[doc_id]
    assert len(points) == chunk_count
    assert all(p.workspace_id == h.workspace_a.id for p in points)

    # 6: search finds the distinctive content with full citation fields
    search = h.client.post(
        "/api/v1/search",
        json={"query": "when does the zephyrine orchid bloom?", "workspace_id": str(h.workspace_a.id)},
        headers=a_headers,
    )
    assert search.status_code == 200
    body = search.json()
    assert DISTINCTIVE in body["context"]
    assert body["sources"], body
    source = body["sources"][0]
    assert source["document_id"] == str(doc_id)
    assert source["filename"] == "notes.txt"
    assert DISTINCTIVE in source["content"]
    assert set(source) == {"chunk_id", "document_id", "filename", "source", "chunk_index", "score", "content"}

    # scoping: document_id narrows; a different document id finds nothing; other users can't search it
    narrowed = h.client.post(
        "/api/v1/search",
        json={"query": "zephyrine orchid", "workspace_id": str(h.workspace_a.id), "document_id": str(doc_id)},
        headers=a_headers,
    )
    assert narrowed.json()["sources"]
    other_doc = h.client.post(
        "/api/v1/search",
        json={"query": "zephyrine orchid", "workspace_id": str(h.workspace_a.id), "document_id": str(uuid.uuid4())},
        headers=a_headers,
    )
    assert other_doc.json()["sources"] == []
    assert h.client.post(
        "/api/v1/search",
        json={"query": "zephyrine orchid", "workspace_id": str(h.workspace_b.id)},
        headers=h.headers(h.user_b),
    ).json()["sources"] == []  # user B's own workspace has none of A's data

    # 7-8: grounded chat answer; the LLM actually received the retrieved context; citations preserved
    chat = h.client.post(
        "/api/v1/chat",
        json={"query": "when does the zephyrine orchid bloom?", "workspace_id": str(h.workspace_a.id)},
        headers=a_headers,
    )
    assert chat.status_code == 200
    chat_body = chat.json()
    assert chat_body["answer"] == "It blooms at midnight [1]."
    assert DISTINCTIVE in h.llm.prompts[-1]
    assert chat_body["sources"][0]["document_id"] == str(doc_id)
    assert chat_body["sources"][0]["filename"] == "notes.txt"
    uuid.UUID(chat_body["conversation_id"])

    # 9-10: delete -> document, chunks, vectors, file, searchability all gone
    stored_before = os.listdir(os.environ["DOCUMENT_STORAGE_PATH"])
    assert len(stored_before) == 1
    deleted = h.client.delete(f"/api/v1/documents/{doc_id}", headers=a_headers)
    assert deleted.status_code == 200
    assert _count(h, Document, Document.id == doc_id) == 0
    assert _count(h, Chunk, Chunk.document_id == doc_id) == 0
    assert doc_id in h.vector_store.deleted_document_ids
    assert doc_id not in h.vector_store.points_by_document
    assert os.listdir(os.environ["DOCUMENT_STORAGE_PATH"]) == []
    assert h.client.get(f"/api/v1/documents/{doc_id}", headers=a_headers).status_code == 404
    after = h.client.post(
        "/api/v1/search",
        json={"query": "zephyrine orchid", "workspace_id": str(h.workspace_a.id)},
        headers=a_headers,
    )
    assert after.json()["sources"] == []


def test_failed_indexing_marks_document_failed_and_keeps_it_deletable(rag, monkeypatch):
    h = rag
    headers = h.headers(h.user_a)
    doc_id = _upload(h, h.user_a, h.workspace_a).json()["id"]

    def broken_embed(texts):
        raise RuntimeError("model exploded")

    import app.services.document_service as document_service_module

    monkeypatch.setattr(document_service_module, "embed_texts", broken_embed)
    response = h.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INGESTION_FAILED"
    assert "model exploded" not in response.text

    # The failure is recorded (not rolled back with the request) and visible to the client.
    assert h.client.get(f"/api/v1/documents/{doc_id}", headers=headers).json()["status"] == "Failed"
    assert h.client.delete(f"/api/v1/documents/{doc_id}", headers=headers).status_code == 200


def test_reindexing_replaces_chunks_and_vectors_without_duplicating(rag):
    h = rag
    headers = h.headers(h.user_a)
    doc_id = uuid.UUID(_upload(h, h.user_a, h.workspace_a).json()["id"])
    first = h.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers).json()
    second = h.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers).json()
    assert first["chunk_count"] == second["chunk_count"]
    assert _count(h, Chunk, Chunk.document_id == doc_id) == second["chunk_count"]
    assert len(h.vector_store.points_by_document[doc_id]) == second["chunk_count"]


def test_workflow_b_conversation_lifecycle_and_ownership(rag):
    h = rag
    a_headers, b_headers = h.headers(h.user_a), h.headers(h.user_b)
    doc_id = _upload(h, h.user_a, h.workspace_a).json()["id"]
    h.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=a_headers)

    # create via chat; both messages persisted in order
    first = h.client.post(
        "/api/v1/chat",
        json={"query": "zephyrine orchid bloom time", "workspace_id": str(h.workspace_a.id)},
        headers=a_headers,
    )
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    assert _count(h, Message, Message.conversation_id == uuid.UUID(conversation_id)) == 2

    history = h.client.get("/api/v1/chat/history", headers=a_headers).json()
    assert [c["id"] for c in history] == [conversation_id]

    detail = h.client.get(f"/api/v1/chat/{conversation_id}", headers=a_headers).json()
    assert detail["id"] == conversation_id
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "zephyrine orchid bloom time"
    assert detail["messages"][1]["content"] == "It blooms at midnight [1]."

    # continuing the conversation appends two more messages and feeds history to the LLM
    second = h.client.post(
        "/api/v1/chat",
        json={
            "query": "and where does it bloom? zephyrine orchid",
            "workspace_id": str(h.workspace_a.id),
            "conversation_id": conversation_id,
        },
        headers=a_headers,
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    assert "zephyrine orchid bloom time" in h.llm.prompts[-1]  # earlier turn is in the prompt
    detail = h.client.get(f"/api/v1/chat/{conversation_id}", headers=a_headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]

    # ownership: user B can neither read, continue, nor delete it, nor see it in history
    assert h.client.get(f"/api/v1/chat/{conversation_id}", headers=b_headers).status_code == 404
    assert h.client.delete(f"/api/v1/chat/{conversation_id}", headers=b_headers).status_code == 404
    hijack = h.client.post(
        "/api/v1/chat",
        json={"query": "anything at all", "workspace_id": str(h.workspace_b.id), "conversation_id": conversation_id},
        headers=b_headers,
    )
    assert hijack.status_code == 404
    assert hijack.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert h.client.get("/api/v1/chat/history", headers=b_headers).json() == []
    assert _count(h, Message, Message.conversation_id == uuid.UUID(conversation_id)) == 4  # untouched

    # delete: 204, then gone, and its messages are removed with it
    assert h.client.delete(f"/api/v1/chat/{conversation_id}", headers=a_headers).status_code == 204
    assert h.client.get(f"/api/v1/chat/{conversation_id}", headers=a_headers).status_code == 404
    assert _count(h, Conversation, Conversation.id == uuid.UUID(conversation_id)) == 0
    assert _count(h, Message, Message.conversation_id == uuid.UUID(conversation_id)) == 0
    assert h.client.get("/api/v1/chat/history", headers=a_headers).json() == []


def test_llm_failure_persists_nothing_and_maps_to_safe_errors(rag):
    h = rag
    headers = h.headers(h.user_a)
    payload = {"query": "zephyrine orchid", "workspace_id": str(h.workspace_a.id)}

    h.llm.error = LLMGenerationError("quota exceeded for key AIza-SECRET", status_code=429)
    limited = h.client.post("/api/v1/chat", json=payload, headers=headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "TOO_MANY_REQUESTS"
    assert "AIza-SECRET" not in limited.text

    h.llm.error = LLMGenerationError("upstream blew up AIza-SECRET", status_code=500)
    failed = h.client.post("/api/v1/chat", json=payload, headers=headers)
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "LLM_GENERATION_FAILED"
    assert "AIza-SECRET" not in failed.text

    # No half-written conversation: the request's transaction was rolled back.
    assert _count(h, Conversation) == 0
    assert _count(h, Message) == 0
    assert h.client.get("/api/v1/chat/history", headers=headers).json() == []
