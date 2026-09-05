"""SearchService: orchestrates the existing retrieval-stage primitives.

Wires together, in the order defined by the LLD pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Cross-Encoder Reranker -> Context Builder

the retrieval components that already exist under `app.retrieval`:
QueryRewriter, HybridRetriever (which itself composes DenseRetriever
and KeywordRetriever), CrossEncoderReranker, and ContextBuilder.

This service does no retrieval, ranking, or context-building logic of
its own - it only calls the existing components in sequence and
passes each one's output to the next. Embedding generation is already
owned by DenseRetriever (it calls the existing `app.embeddings.embed_text`
internally), so this service never touches the embedding API directly.
Workspace/document scoping is already enforced by DenseRetriever and
KeywordRetriever - there is no separate MetadataFilter here, since
inspection of those two didn't surface any scoping gap for this
service to fill.
"""

from dataclasses import dataclass
from typing import Optional

from app.retrieval.context_builder import BuiltContext, ContextBuilder
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.query_rewriter import QueryRewriter, RewrittenQuery
from app.retrieval.reranker import CrossEncoderReranker
from app.retrieval.validation import DEFAULT_TOP_K, UUIDLike


@dataclass
class SearchResult:
    """SearchService's output: the query as actually run, plus the built
    context and source metadata produced from it.

    Composed entirely from existing retrieval-package types
    (RewrittenQuery, BuiltContext) rather than duplicating their
    fields.
    """

    query: RewrittenQuery
    context: BuiltContext


class SearchService:
    """Thin orchestrator over the existing retrieval primitives.

    Holds only the already-constructed components it's given - it
    creates no database/vector-store connections and duplicates no
    retrieval, reranking, or context-building logic. Safe to construct
    once and reuse across multiple search() calls.
    """

    def __init__(
        self,
        query_rewriter: QueryRewriter,
        hybrid_retriever: HybridRetriever,
        reranker: CrossEncoderReranker,
        context_builder: ContextBuilder,
    ):
        self.query_rewriter = query_rewriter
        self.hybrid_retriever = hybrid_retriever
        self.reranker = reranker
        self.context_builder = context_builder

    async def search(
        self,
        query: str,
        workspace_id: UUIDLike,
        *,
        document_id: Optional[UUIDLike] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> SearchResult:
        """Run the full retrieval-stage pipeline for `query`, scoped to
        `workspace_id` (and, if given, `document_id`).

        Order of operations:
        1. QueryRewriter normalizes the raw query (deterministic,
           no LLM).
        2. HybridRetriever runs dense + keyword retrieval concurrently
           over the normalized query and fuses them with RRF -
           DenseRetriever generates the query embedding internally via
           the existing embedding engine, so no embedding step is
           performed here.
        3. CrossEncoderReranker re-scores and re-sorts the fused
           candidates against the normalized query.
        4. ContextBuilder assembles the reranked results into a single
           context string plus structured source metadata.

        workspace_id (and document_id, if given) are passed through
        unchanged to HybridRetriever, which enforces scoping via
        DenseRetriever/KeywordRetriever exactly as it already does -
        this method neither widens nor re-derives that scope.

        top_k is passed through to both HybridRetriever and
        CrossEncoderReranker unchanged, so each component's own
        existing top_k validation (via the shared validation helpers)
        applies as-is; this method performs no additional top_k
        handling of its own.

        Raises whatever the underlying components raise -
        RetrievalValidationError for invalid input, EmbeddingError or
        QdrantIntegrationError from dense retrieval, database errors
        from keyword retrieval, or RerankerError from reranking - none
        of these are caught or swallowed here.
        """
        rewritten_query = self.query_rewriter.rewrite(query)

        hybrid_results = await self.hybrid_retriever.search(
            rewritten_query.normalized,
            workspace_id,
            document_id=document_id,
            top_k=top_k,
        )

        reranked_results = self.reranker.rerank(
            rewritten_query.normalized,
            hybrid_results,
            top_k=top_k,
        )

        context = self.context_builder.build_context(reranked_results)

        return SearchResult(query=rewritten_query, context=context)