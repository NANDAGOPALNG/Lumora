"""Retrieval primitives for Lumora.

Exposes dense (embedding-similarity, Qdrant) retrieval, keyword
(PostgreSQL full-text) retrieval, hybrid (RRF-fused) retrieval, and
cross-encoder reranking as composable primitives. Context building is
a separate, later stage and belongs in its own module - this package
is not wired into any API route or SearchService yet.
"""

from app.retrieval.dense_retriever import DenseRetriever, DenseSearchResult
from app.retrieval.hybrid_retriever import HybridRetriever, HybridSearchResult
from app.retrieval.keyword_retriever import KeywordRetriever, KeywordSearchResult
from app.retrieval.reranker import CrossEncoderReranker, RerankedResult, RerankerError
from app.retrieval.validation import DEFAULT_TOP_K, MAX_TOP_K, RetrievalValidationError

__all__ = [
    "DenseRetriever",
    "DenseSearchResult",
    "KeywordRetriever",
    "KeywordSearchResult",
    "HybridRetriever",
    "HybridSearchResult",
    "CrossEncoderReranker",
    "RerankedResult",
    "RerankerError",
    "RetrievalValidationError",
    "DEFAULT_TOP_K",
    "MAX_TOP_K",
]
