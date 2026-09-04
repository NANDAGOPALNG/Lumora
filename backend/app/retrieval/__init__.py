"""Retrieval primitives for Lumora.

Currently exposes only dense (embedding-similarity) retrieval over
Qdrant. Keyword/BM25 retrieval, score fusion, reranking, and context
building are separate, later stages and belong in their own modules -
this package is not wired into any API route or SearchService yet.
"""

from app.retrieval.dense_retriever import (
    DEFAULT_TOP_K,
    MAX_TOP_K,
    DenseRetriever,
    DenseSearchResult,
    RetrievalValidationError,
)

__all__ = [
    "DenseRetriever",
    "DenseSearchResult",
    "RetrievalValidationError",
    "DEFAULT_TOP_K",
    "MAX_TOP_K",
]
