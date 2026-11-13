"""Stage 4: the fresh Jina + Qdrant + R2 stack, end to end.

Real code throughout - document service, chunking, the Jina embedding
engine, QdrantVectorStore (qdrant-client's in-memory engine), DenseRetriever,
the Jina reranker, the context builder, R2Storage's call shapes (in-memory fake
S3). The ONLY things replaced are the network edges: Jina's HTTP API (a mock
transport that returns deterministic 1024-dimension vectors and scores) and S3.
PostgreSQL full-text search can't run on SQLite, so keyword search is stubbed
to "no hits" exactly as in the existing search tests; retrieval is dense-only.
"""

import asyncio
import json
import math
import re
import uuid
import zlib
from pathlib import Path

import httpx
import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

import app.services.document_service as document_service_module  # noqa: F401
from app.models.document import DocumentStatus
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.retrieval import ContextBuilder, DenseRetriever, HybridRetriever, KeywordRetriever, QueryRewriter
from app.retrieval.reranker import CrossEncoderReranker
from app.services.document_service import DocumentService, IngestionFailedError
from app.services.search_service import SearchService
from app.storage import factory
from app.vector_store import QdrantIntegrationError, QdrantVectorStore
from app.vector_store.store import COLLECTION_NAME
from tests._r2_support import BUCKET, fake_r2  # noqa: F401  (fake_r2 is a fixture)
from tests.test_storage_workflows import make_world

JINA_KEY = "jina-test-key-abc123"
BACKEND_ROOT = Path(__file__).resolve().parent.parent

LEAVE_DOC = ("Annual leave policy. Every employee receives twenty five days of annual leave per year. "
             "Unused annual leave may be carried over for three months. ") * 6
EXPENSE_DOC = ("Expense policy. Travel expenses are reimbursed within thirty days after receipts are submitted. "
               "Meals during business travel are capped per day. ") * 6


# --------------------------------------------------------------------------- the mocked Jina API


def embed_text_deterministically(text: str) -> list:
    """A 1024-dimension bag-of-words vector (unit length): texts that share
    words are close in cosine distance, so retrieval is genuinely meaningful."""
    vec = [0.0] * 1024
    for token in re.findall(r"\w+", text.lower()):
        vec[zlib.crc32(token.encode()) % 1024] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    if norm == 1.0 and not any(vec):
        vec[0] = 1.0
    return [v / norm for v in vec]


class JinaMock:
    def __init__(self):
        self.embedding_requests = []
        self.rerank_requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        record = {"url": str(request.url), "auth": request.headers.get("authorization"), "body": body}
        if request.url.path.endswith("/v1/embeddings"):
            self.embedding_requests.append(record)
            return httpx.Response(200, json={
                "data": [{"index": i, "embedding": embed_text_deterministically(t)} for i, t in enumerate(body["input"])]
            })
        if request.url.path.endswith("/v1/rerank"):
            self.rerank_requests.append(record)
            query_words = set(re.findall(r"\w+", body["query"].lower()))
            scores = [len(query_words & set(re.findall(r"\w+", d.lower()))) / (len(query_words) or 1)
                      for d in body["documents"]]
            return httpx.Response(200, json={
                "results": [{"index": i, "relevance_score": s} for i, s in enumerate(scores)]
            })
        return httpx.Response(404)

    @property
    def embedding_models_used(self):
        return {r["body"]["model"] for r in self.embedding_requests}


class DenseOnlyKeywordRetriever(KeywordRetriever):
    """Keyword *search* needs PostgreSQL; `load_contents` stays the real SQL."""

    async def search(self, *args, **kwargs):
        return []


@pytest.fixture
def stack(monkeypatch, tmp_path, fake_r2):
    """Jina mock + in-memory Qdrant + R2 fake, wired into the real code."""
    monkeypatch.setenv("JINA_API_KEY", JINA_KEY)
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "local"))
    factory.reset_cache()

    jina = JinaMock()
    real_client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *args, **kwargs: real_client_class(transport=httpx.MockTransport(jina.handler), timeout=kwargs.get("timeout")),
    )

    store = QdrantVectorStore()
    store._client = AsyncQdrantClient(":memory:")

    class Stack:
        pass

    s = Stack()
    s.jina, s.store, s.r2 = jina, store, fake_r2
    yield s
    factory.reset_cache()


def document_service(world, session, store):
    return DocumentService(
        DocumentRepository(session), WorkspaceRepository(session), ChunkRepository(session), store
    )


async def upload_and_index(world, session, store, filename, text):
    service = document_service(world, session, store)
    created = await service.upload_document(
        workspace_id=world.workspace.id, user_id=world.user.id, filename=filename,
        content_type=None, content=text.encode(),
    )
    indexed = await service.reindex_document_for_user(created.id, world.user.id)
    return created, indexed


async def all_points(store):
    points, _ = await store._get_client().scroll(COLLECTION_NAME, limit=1000, with_payload=True, with_vectors=True)
    return points


def scenario(coro_fn):
    async def runner():
        world = await make_world()
        try:
            return await coro_fn(world)
        finally:
            await world.engine.dispose()

    return asyncio.run(runner())


# =========================================================================== fresh collection


def test_a_fresh_collection_is_created_on_first_use_with_1024_cosine(stack):
    async def go(world):
        async with world.session_factory() as session:
            assert not await stack.store._get_client().collection_exists(COLLECTION_NAME)
            await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            info = await stack.store._get_client().get_collection(COLLECTION_NAME)
            return info.config.params.vectors

    vectors = scenario(go)
    assert vectors.size == 1024 and vectors.distance == qmodels.Distance.COSINE


def test_an_existing_incompatible_collection_is_never_reset_automatically(stack):
    async def go(world):
        client = stack.store._get_client()
        await client.create_collection(COLLECTION_NAME, vectors_config=qmodels.VectorParams(size=384, distance=qmodels.Distance.COSINE))
        await client.upsert(COLLECTION_NAME, [qmodels.PointStruct(id=str(uuid.uuid4()), vector=[0.1] * 384)], wait=True)
        async with world.session_factory() as session:
            with pytest.raises(IngestionFailedError) as excinfo:
                await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            # The indexing failure is reported (document marked failed) and its cause is the config check.
            assert isinstance(excinfo.value.__cause__, QdrantIntegrationError)
            assert "incompatible" in str(excinfo.value.__cause__)
        info = await client.get_collection(COLLECTION_NAME)
        return info.config.params.vectors.size, (await client.count(COLLECTION_NAME, exact=True)).count

    size, points = scenario(go)
    assert size == 384 and points == 1  # untouched: the app only reports, it never recreates


# =========================================================================== embeddings use Jina


def test_upload_and_reindex_embed_with_jina_and_store_1024_dim_vectors(stack):
    async def go(world):
        async with world.session_factory() as session:
            created, indexed = await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            return created, indexed, await all_points(stack.store)

    created, indexed, points = scenario(go)
    assert indexed.status == DocumentStatus.INDEXED and len(points) == indexed.chunk_count > 0

    assert stack.jina.embedding_models_used == {"jina-embeddings-v3"}
    for request in stack.jina.embedding_requests:
        assert request["url"] == "https://api.jina.ai/v1/embeddings"
        assert request["auth"] == f"Bearer {JINA_KEY}"
        assert request["body"]["task"] == "retrieval.passage" and request["body"]["dimensions"] == 1024
    for point in points:
        assert len(point.vector) == 1024
        assert point.payload["embedding_model"] == "jina-embeddings-v3"  # provenance marker on every new point
        assert point.payload["document_id"] == str(created.id)


def test_reindexing_replaces_vectors_without_duplicates_and_uses_jina_again(stack):
    async def go(world):
        async with world.session_factory() as session:
            created, first = await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            requests_after_first = len(stack.jina.embedding_requests)
            ids_first = {p.id for p in await all_points(stack.store)}
            second = await document_service(world, session, stack.store).reindex_document_for_user(created.id, world.user.id)
            return first, second, requests_after_first, ids_first, await all_points(stack.store)

    first, second, before, ids_first, points = scenario(go)
    assert len(stack.jina.embedding_requests) > before  # reindex called Jina again
    assert len(points) == second.chunk_count == first.chunk_count  # no duplicates, none orphaned
    assert {p.id for p in points}.isdisjoint(ids_first)  # fresh chunk ids; the old points are gone
    assert stack.jina.embedding_models_used == {"jina-embeddings-v3"}


def test_reindexing_updated_r2_content_replaces_the_searchable_text(stack):
    async def go(world):
        async with world.session_factory() as session:
            created, _ = await upload_and_index(world, session, stack.store, "policy.txt", LEAVE_DOC)
            stack.r2.s3.objects[(BUCKET, f"documents/{created.id}.txt")] = EXPENSE_DOC.encode()
            await document_service(world, session, stack.store).reindex_document_for_user(created.id, world.user.id)
            service = SearchService(QueryRewriter(), HybridRetriever(DenseRetriever(stack.store), DenseOnlyKeywordRetriever(session)),
                                    CrossEncoderReranker(), ContextBuilder())
            return await service.search("travel expenses reimbursed receipts", world.workspace.id)

    result = scenario(go)
    assert "Travel expenses are reimbursed" in result.context.text
    assert "annual leave" not in result.context.text.lower()


# =========================================================================== retrieval + reranking


def test_search_embeds_the_query_with_jina_retrieves_from_qdrant_and_reranks_with_jina(stack):
    async def go(world):
        async with world.session_factory() as session:
            await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            await upload_and_index(world, session, stack.store, "expenses.txt", EXPENSE_DOC)
            service = SearchService(QueryRewriter(), HybridRetriever(DenseRetriever(stack.store), DenseOnlyKeywordRetriever(session)),
                                    CrossEncoderReranker(), ContextBuilder())
            return await service.search("How many days of annual leave do I get?", world.workspace.id)

    result = scenario(go)

    # Retrieval and ranking found the right document...
    assert result.context.sources and result.context.sources[0].filename == "leave.txt"
    assert "twenty five days of annual leave" in result.context.text

    # ...with a query embedded as a *query* (not a passage) by the Jina model...
    query_requests = [r for r in stack.jina.embedding_requests if r["body"]["task"] == "retrieval.query"]
    assert len(query_requests) == 1 and query_requests[0]["body"]["model"] == "jina-embeddings-v3"
    assert query_requests[0]["body"]["dimensions"] == 1024

    # ...and reranked by the Jina reranker with the retrieved chunk texts.
    assert len(stack.jina.rerank_requests) == 1
    rerank = stack.jina.rerank_requests[0]
    assert rerank["url"] == "https://api.jina.ai/v1/rerank" and rerank["auth"] == f"Bearer {JINA_KEY}"
    assert rerank["body"]["model"] == "jina-reranker-v2-base-multilingual"
    assert rerank["body"]["documents"] and all(isinstance(d, str) and d for d in rerank["body"]["documents"])


def test_search_is_scoped_to_the_workspace(stack):
    async def go(world):
        async with world.session_factory() as session:
            await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            service = SearchService(QueryRewriter(), HybridRetriever(DenseRetriever(stack.store), DenseOnlyKeywordRetriever(session)),
                                    CrossEncoderReranker(), ContextBuilder())
            return await service.search("annual leave", uuid.uuid4())  # some other workspace

    assert scenario(go).context.sources == []


# =========================================================================== deletion


def test_deleting_a_document_removes_its_vectors_and_r2_object_but_not_others(stack):
    async def go(world):
        async with world.session_factory() as session:
            leave, _ = await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            expenses, expenses_indexed = await upload_and_index(world, session, stack.store, "expenses.txt", EXPENSE_DOC)
            before = await all_points(stack.store)
            deleted = await document_service(world, session, stack.store).delete_document_for_user(leave.id, world.user.id)
            row = await DocumentRepository(session).get_by_id_and_workspace_owner(leave.id, world.user.id)
            return leave, expenses, expenses_indexed, before, deleted, row, await all_points(stack.store)

    leave, expenses, expenses_indexed, before, deleted, row, after = scenario(go)
    assert deleted is True and row is None
    assert {p.payload["document_id"] for p in before} == {str(leave.id), str(expenses.id)}
    assert {p.payload["document_id"] for p in after} == {str(expenses.id)}  # only the other document remains
    assert len(after) == expenses_indexed.chunk_count
    assert sorted(stack.r2.s3.keys()) == [f"documents/{expenses.id}.txt"]  # the R2 object is gone, the other kept


def test_deleting_the_last_document_leaves_an_empty_valid_collection(stack):
    async def go(world):
        async with world.session_factory() as session:
            created, _ = await upload_and_index(world, session, stack.store, "leave.txt", LEAVE_DOC)
            await document_service(world, session, stack.store).delete_document_for_user(created.id, world.user.id)
            client = stack.store._get_client()
            info = await client.get_collection(COLLECTION_NAME)
            return info.config.params.vectors, (await client.count(COLLECTION_NAME, exact=True)).count

    vectors, count = scenario(go)
    assert count == 0 and vectors.size == 1024


# =========================================================================== guards: no old models, no automatic reset

FORBIDDEN_IMPORTS = re.compile(r"^\s*(import|from)\s+(torch|transformers|sentence_transformers|FlagEmbedding)\b", re.M)
OLD_MODEL_NAMES = re.compile(r"bge|baai|sentence[-_]transformers|flagembedding", re.I)


def _source_files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_old_model_imports_or_names_remain_in_the_active_backend_code():
    offenders = []
    for path in _source_files(BACKEND_ROOT / "app") + [BACKEND_ROOT / "main.py"]:
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN_IMPORTS.search(text) or OLD_MODEL_NAMES.search(text):
            offenders.append(str(path.relative_to(BACKEND_ROOT)))
    assert offenders == []

    # The operator script may *name* the old model (detecting it is its job),
    # but must never import it.
    for path in _source_files(BACKEND_ROOT / "scripts"):
        assert not FORBIDDEN_IMPORTS.search(path.read_text(encoding="utf-8")), path.name


def test_no_old_model_packages_are_declared_or_locked():
    pyproject = (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    lock = (BACKEND_ROOT / "uv.lock").read_text(encoding="utf-8")
    for package in ("sentence-transformers", "torch", "transformers", "flagembedding"):
        assert package not in pyproject
        assert f'name = "{package}"' not in lock


def test_only_the_admin_script_can_delete_a_qdrant_collection():
    deleters = [
        str(p.relative_to(BACKEND_ROOT))
        for p in _source_files(BACKEND_ROOT / "app") + [BACKEND_ROOT / "main.py"]
        if re.search(r"delete_collection|recreate_collection", p.read_text(encoding="utf-8"))
    ]
    assert deleters == []  # the application can never drop or recreate the collection
    admin_source = (BACKEND_ROOT / "scripts" / "qdrant_admin.py").read_text(encoding="utf-8")
    assert admin_source.count("delete_collection(") == 1  # the one guarded call, inside reset_collection
