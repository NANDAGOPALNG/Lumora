"""Retrieval primitives for Lumora.

Exposes dense (embedding-similarity, Qdrant) retrieval and keyword
(PostgreSQL full-text) retrieval as independent primitives. Hybrid
score fusion, reranking, and context building are separate, later
stages and belong in their own modules - this package is not wired
into any API route or SearchService yet.
"""

from app.retrieval.dense_retriever import DenseRetriever, DenseSearchResult
from app.retrieval.keyword_retriever import KeywordRetriever, KeywordSearchResult
from app.retrieval.validation import DEFAULT_TOP_K, MAX_TOP_K, RetrievalValidationError

__all__ = [
    "DenseRetriever",
    "DenseSearchResult",
    "KeywordRetriever",
    "KeywordSearchResult",
    "RetrievalValidationError",
    "DEFAULT_TOP_K",
    "MAX_TOP_K",
]
