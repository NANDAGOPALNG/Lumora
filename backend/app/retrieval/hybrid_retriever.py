"""Hybrid retrieval: fuse DenseRetriever and KeywordRetriever via
Reciprocal Rank Fusion (RRF).

Implements only the "Hybrid Retriever" stage of the larger LLD pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Cross-Encoder Reranker -> Context Builder

Query rewriting, reranking, context building, and API wiring are
separate, later stages and are not implemented here. This module
never touches Qdrant or PostgreSQL directly - it only composes the
two existing retrievers and combines their already-scored result
lists.

Not wired into any API route yet: this is a reusable primitive meant
to be composed by a future SearchService, the same as DenseRetriever
and KeywordRetriever.
"""

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional
from uuid import UUID

from app.retrieval.dense_retriever import DenseRetriever, DenseSearchResult
from app.retrieval.keyword_retriever import KeywordRetriever, KeywordSearchResult
from app.retrieval.validation import (
    DEFAULT_TOP_K,
    UUIDLike,
    validate_query,
    validate_top_k,
    validate_uuid,
)

# Standard RRF constant and equal starting weights for the two lists -
# weighting/tuning is left for later, this task only wires fusion up.
RRF_K = 60
DENSE_WEIGHT = 1.0
KEYWORD_WEIGHT = 1.0


@dataclass
class HybridSearchResult:
    """A single fused hybrid-retrieval hit.

    `content` is populated when available from KeywordRetriever (which
    already has chunk text on hand from PostgreSQL) and is None for
    chunks that only appeared in the dense result list, since
    DenseSearchResult deliberately carries no chunk text.
    """

    chunk_id: UUID
    document_id: UUID
    workspace_id: UUID
    filename: str
    chunk_index: int
    source: str
    score: float
    content: Optional[str] = None


@dataclass
class _FusionEntry:
    """Internal accumulator: one per unique chunk_id while combining
    RRF contributions across the two result lists.
    """

    metadata: object  # DenseSearchResult or KeywordSearchResult, metadata fields only
    content: Optional[str]
    rrf_score: float = 0.0


def _accumulate(
    entries: Dict[UUID, _FusionEntry],
    results: List,
    weight: float,
    has_content: bool,
) -> None:
    """Add one retriever's ranked results into the shared accumulator.

    Rank is 1-based position in `results` (already sorted by that
    retriever's own score, descending). If a chunk_id was already seen
    from the other list, its RRF contribution is added to the existing
    entry rather than creating a duplicate; metadata/content from the
    list processed first for that chunk_id is kept as-is, so selection
    is deterministic rather than arbitrarily overwritten.
    """
    for rank, result in enumerate(results, start=1):
        contribution = weight / (RRF_K + rank)
        existing = entries.get(result.chunk_id)
        if existing is None:
            entries[result.chunk_id] = _FusionEntry(
                metadata=result,
                content=(result.content if has_content else None),
                rrf_score=contribution,
            )
        else:
            existing.rrf_score += contribution
            if existing.content is None and has_content:
                existing.content = result.content


def _to_hybrid_result(chunk_id: UUID, entry: _FusionEntry) -> HybridSearchResult:
    metadata = entry.metadata
    return HybridSearchResult(
        chunk_id=chunk_id,
        document_id=metadata.document_id,
        workspace_id=metadata.workspace_id,
        filename=metadata.filename,
        chunk_index=metadata.chunk_index,
        source=metadata.source,
        score=entry.rrf_score,
        content=entry.content,
    )


class HybridRetriever:
    """Combines DenseRetriever and KeywordRetriever results via Reciprocal
    Rank Fusion.

    Thin composition of the two existing retrievers - holds no
    database/vector-store connections of its own and creates none;
    both retrievers are constructed and owned by the caller, the same
    lifecycle DenseRetriever and KeywordRetriever already use.
    """

    def __init__(self, dense_retriever: DenseRetriever, keyword_retriever: KeywordRetriever):
        self.dense_retriever = dense_retriever
        self.keyword_retriever = keyword_retriever

    async def search(
        self,
        query: str,
        workspace_id: UUIDLike,
        *,
        document_id: Optional[UUIDLike] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> List[HybridSearchResult]:
        """Run dense and keyword retrieval concurrently over the same
        query/workspace/document scope, fuse their ranked results with
        RRF, deduplicate by chunk_id, and return the top_k fused
        results sorted by hybrid score descending (chunk_id ascending
        breaks ties for deterministic ordering).

        top_k is applied after fusion and deduplication, against the
        full union of chunks from both lists - not against each
        underlying list before combining.

        Returns [] only when both underlying retrievers return [];
        this is not an error. Validation errors and any exception
        raised by either underlying retriever (embedding failure,
        Qdrant failure, database failure) propagate unchanged - this
        method never swallows them.
        """
        # Validate once here using the same shared helpers the
        # underlying retrievers use, so both retrievers are always
        # called with an already-valid, identical scope.
        validated_query = validate_query(query)
        workspace_uuid = validate_uuid(workspace_id, "workspace_id")
        document_uuid = (
            validate_uuid(document_id, "document_id") if document_id is not None else None
        )
        resolved_top_k = validate_top_k(top_k)

        dense_results: List[DenseSearchResult]
        keyword_results: List[KeywordSearchResult]
        dense_results, keyword_results = await asyncio.gather(
            self.dense_retriever.search(
                validated_query,
                workspace_uuid,
                document_id=document_uuid,
                top_k=resolved_top_k,
            ),
            self.keyword_retriever.search(
                validated_query,
                workspace_uuid,
                document_id=document_uuid,
                top_k=resolved_top_k,
            ),
        )

        entries: Dict[UUID, _FusionEntry] = {}
        _accumulate(entries, dense_results, DENSE_WEIGHT, has_content=False)
        _accumulate(entries, keyword_results, KEYWORD_WEIGHT, has_content=True)

        fused = [
            _to_hybrid_result(chunk_id, entry) for chunk_id, entry in entries.items()
        ]
        fused.sort(key=lambda r: (-r.score, str(r.chunk_id)))

        return fused[:resolved_top_k]
