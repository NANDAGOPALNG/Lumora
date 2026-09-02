"""Embedding engine: text -> BGE-M3 dense vectors.

Reusable module only - not connected to the database, Qdrant, or any
API route. See `engine.py` for `embed_text` / `embed_texts`.
"""

from app.embeddings.engine import (
    EMBEDDING_DIMENSION,
    EmbeddingError,
    embed_text,
    embed_texts,
)

__all__ = ["embed_text", "embed_texts", "EmbeddingError", "EMBEDDING_DIMENSION"]
