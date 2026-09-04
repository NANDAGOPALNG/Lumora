"""Dense vector retrieval: query text -> BGE-M3 embedding -> Qdrant search.

Implements only the "dense retrieval" stage of the larger LLD pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Cross-Encoder Reranker -> Context Builder

Query rewriting, keyword/BM25 search, score fusion, reranking, and
context building are separate, later stages and are not implemented
here. This module does not read or write PostgreSQL - results are
built entirely from the Qdrant payload already stored alongside each
vector; hydrating chunk content from PostgreSQL is a later stage.

Not wired into any API route yet: this is a reusable primitive meant
to be composed by a future SearchService.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Union
from uuid import UUID

from qdrant_client.http import models as qmodels

from app.embeddings import embed_text
from app.vector_store import QdrantVectorStore

# Sensible default and hard ceiling for top_k, so a caller can't
# accidentally (or maliciously) request an unbounded number of points
# back from Qdrant.
DEFAULT_TOP_K = 5
MAX_TOP_K = 50

UUIDLike = Union[UUID, str]


class RetrievalValidationError(Exception):
    """Raised when dense_search() is called with invalid input."""


@dataclass
class DenseSearchResult:
    """A single dense-retrieval hit, built entirely from the Qdrant payload.

    Deliberately excludes chunk text - the existing Qdrant payload
    doesn't store it, and hydrating content from PostgreSQL is left to
    a later retrieval stage.
    """

    chunk_id: UUID
    document_id: UUID
    workspace_id: UUID
    filename: str
    chunk_index: int
    source: str
    score: float


def _validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise RetrievalValidationError("query must be a non-empty string")
    return query


def _validate_uuid(value: UUIDLike, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise RetrievalValidationError(f"{field_name} must be a valid UUID") from exc


def _validate_top_k(top_k: int) -> int:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise RetrievalValidationError("top_k must be a positive integer")
    return min(top_k, MAX_TOP_K)


def _build_filter(workspace_id: UUID, document_id: Optional[UUID]) -> qmodels.Filter:
    """Every dense search is scoped to a workspace; an optional document_id
    narrows further but never replaces the workspace_id condition - both
    are combined with AND (Qdrant's `must`), never document_id alone.
    """
    must: List[qmodels.FieldCondition] = [
        qmodels.FieldCondition(
            key="workspace_id", match=qmodels.MatchValue(value=str(workspace_id))
        )
    ]
    if document_id is not None:
        must.append(
            qmodels.FieldCondition(
                key="document_id", match=qmodels.MatchValue(value=str(document_id))
            )
        )
    return qmodels.Filter(must=must)


def _to_result(point: qmodels.ScoredPoint) -> DenseSearchResult:
    payload = point.payload or {}
    return DenseSearchResult(
        chunk_id=UUID(str(payload["chunk_id"])),
        document_id=UUID(str(payload["document_id"])),
        workspace_id=UUID(str(payload["workspace_id"])),
        filename=payload["filename"],
        chunk_index=payload["chunk_index"],
        source=payload["source"],
        score=point.score,
    )


class DenseRetriever:
    """Dense (embedding-similarity) retrieval over the `knowledge_chunks`
    Qdrant collection, scoped to a workspace.

    Thin composition of the existing embedding engine and
    QdrantVectorStore - holds no state of its own beyond the
    vector-store instance it's given, and is safe to reuse across
    requests/queries.
    """

    def __init__(self, vector_store: QdrantVectorStore):
        self.vector_store = vector_store

    async def search(
        self,
        query: str,
        workspace_id: UUIDLike,
        *,
        document_id: Optional[UUIDLike] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> List[DenseSearchResult]:
        """Embed `query` and return the top_k most similar chunks in
        `workspace_id` (and, if given, `document_id`).

        Returns [] when there are no matching points - this is not an
        error. Raises RetrievalValidationError for invalid input,
        EmbeddingError if BGE-M3 embedding generation fails, and
        QdrantIntegrationError if the Qdrant search itself fails, so a
        genuine failure is always distinguishable from an empty result.

        workspace_id must come from the authenticated/application layer
        (e.g. the caller's verified workspace membership) - this method
        applies it as-is and never infers or widens it, so results from
        another workspace are never returned.
        """
        validated_query = _validate_query(query)
        workspace_uuid = _validate_uuid(workspace_id, "workspace_id")
        document_uuid = (
            _validate_uuid(document_id, "document_id") if document_id is not None else None
        )
        resolved_top_k = _validate_top_k(top_k)

        query_vector = embed_text(validated_query)
        query_filter = _build_filter(workspace_uuid, document_uuid)

        points = await self.vector_store.search(
            query_vector=query_vector,
            query_filter=query_filter,
            limit=resolved_top_k,
        )

        return [_to_result(point) for point in points]
