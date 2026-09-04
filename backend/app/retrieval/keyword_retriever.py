"""Keyword retrieval: PostgreSQL full-text (BM25-style) search over chunks.

Implements only the "keyword/BM25 retrieval" primitive of the larger
LLD pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Cross-Encoder Reranker -> Context Builder

Hybrid score fusion, reranking, query rewriting, and API wiring are
separate, later stages and are not implemented here. This module does
not touch Qdrant and does not generate embeddings - it reads only the
existing `chunks`/`documents` tables via the existing async SQLAlchemy
session.

Ranking uses PostgreSQL's native text-search functions
(`websearch_to_tsquery` + `ts_rank`) computed on `Chunk.content` at
query time. No schema change, no generated tsvector column, and no
third-party BM25 dependency were needed.

Not wired into any API route yet: this is a reusable primitive meant
to be composed by a future SearchService, the same as DenseRetriever.
"""

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.retrieval.validation import (
    DEFAULT_TOP_K,
    UUIDLike,
    validate_query,
    validate_top_k,
    validate_uuid,
)

# PostgreSQL text-search configuration used for both the document side
# (to_tsvector) and the query side (websearch_to_tsquery). Hardcoded
# rather than pulled from Settings, since no text-search language
# configuration exists elsewhere in the project yet.
TEXT_SEARCH_CONFIG = "english"


@dataclass
class KeywordSearchResult:
    """A single keyword-retrieval hit.

    Field set matches DenseSearchResult (chunk_id, document_id,
    workspace_id, filename, chunk_index, source, score) as closely as
    practical, plus `content`: keyword search already has the chunk
    text on hand from PostgreSQL, so it's included here rather than
    discarded. DenseSearchResult itself is left unchanged.
    """

    chunk_id: UUID
    document_id: UUID
    workspace_id: UUID
    filename: str
    chunk_index: int
    source: str
    score: float
    content: str


class KeywordRetriever:
    """Keyword/BM25-style retrieval over the `chunks` table, scoped to a workspace.

    Holds only the AsyncSession it's given - safe to construct per
    request/unit-of-work, the same lifecycle as the other repositories
    in this project.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(
        self,
        query: str,
        workspace_id: UUIDLike,
        *,
        document_id: Optional[UUIDLike] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> List[KeywordSearchResult]:
        """Rank chunks in `workspace_id` (and, if given, `document_id`) by
        PostgreSQL full-text relevance to `query`, descending.

        Returns [] when nothing matches - this is not an error. Raises
        RetrievalValidationError for invalid input; database errors
        from the underlying query are never swallowed.

        workspace_id must come from the authenticated/application
        layer, the same as DenseRetriever - this method applies it as
        a mandatory filter (via a join to Document, which already
        carries workspace_id - no workspace data is duplicated onto
        Chunk) and never infers or widens it, so results from another
        workspace are never returned. An optional document_id narrows
        further but is always combined with the workspace filter, never
        used on its own.
        """
        validated_query = validate_query(query)
        workspace_uuid = validate_uuid(workspace_id, "workspace_id")
        document_uuid = (
            validate_uuid(document_id, "document_id") if document_id is not None else None
        )
        resolved_top_k = validate_top_k(top_k)

        tsquery = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, validated_query)
        tsvector = func.to_tsvector(TEXT_SEARCH_CONFIG, Chunk.content)
        rank = func.ts_rank(tsvector, tsquery).label("score")

        stmt = (
            select(
                Chunk.id.label("chunk_id"),
                Chunk.document_id.label("document_id"),
                Chunk.chunk_index.label("chunk_index"),
                Chunk.content.label("content"),
                Document.workspace_id.label("workspace_id"),
                Document.filename.label("filename"),
                Document.file_type.label("source"),
                rank,
            )
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.workspace_id == workspace_uuid)
            .where(tsvector.op("@@")(tsquery))
        )

        if document_uuid is not None:
            stmt = stmt.where(Chunk.document_id == document_uuid)

        stmt = stmt.order_by(rank.desc()).limit(resolved_top_k)

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            KeywordSearchResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                workspace_id=row.workspace_id,
                filename=row.filename,
                chunk_index=row.chunk_index,
                source=row.source,
                score=float(row.score),
                content=row.content,
            )
            for row in rows
        ]
