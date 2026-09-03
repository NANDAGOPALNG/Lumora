"""Qdrant vector-store integration.

Reusable module only - not wired into DocumentService, the reindex
endpoint, PostgreSQL repositories, the embedding engine, or any API
route yet.
"""

from app.vector_store.store import (
    COLLECTION_NAME,
    VECTOR_DISTANCE,
    VECTOR_SIZE,
    QdrantChunkPoint,
    QdrantIntegrationError,
    QdrantVectorStore,
)

__all__ = [
    "QdrantVectorStore",
    "QdrantChunkPoint",
    "QdrantIntegrationError",
    "COLLECTION_NAME",
    "VECTOR_SIZE",
    "VECTOR_DISTANCE",
]
