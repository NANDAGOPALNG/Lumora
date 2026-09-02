"""BGE-M3 embedding engine.

Converts text into dense BGE-M3 embeddings (1024 dimensions) via
sentence-transformers. Independent of FastAPI, PostgreSQL, and Qdrant -
this module only turns text into vectors; nothing here reads or writes
any database, and it isn't wired into any route yet.
"""

import threading
from typing import List, Optional

from app.config.settings import Settings

EMBEDDING_DIMENSION = 1024

_model = None
_model_lock = threading.Lock()


class EmbeddingError(Exception):
    """Raised when the embedding model fails to load, or embedding generation
    fails, or invalid input is provided."""


def _load_model():
    """Lazily load and cache the BGE-M3 SentenceTransformer model.

    Loaded once per process, on first use - not at module import time,
    and not repeated on every embed_texts()/embed_text() call.
    """
    global _model

    if _model is not None:
        return _model

    with _model_lock:
        # Re-check inside the lock: another thread may have finished
        # loading while we were waiting for it.
        if _model is not None:
            return _model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError(
                "sentence-transformers is not installed; cannot load the embedding model"
            ) from exc

        settings = Settings.get_instance()

        try:
            # device=None -> sentence-transformers selects GPU automatically
            # when available, otherwise CPU. Never hard-coded here.
            loaded_model = SentenceTransformer(settings.embedding_model_name)
        except Exception as exc:
            raise EmbeddingError(
                f"Failed to load embedding model '{settings.embedding_model_name}'"
            ) from exc

        _model = loaded_model

    return _model


def _validate_texts(texts) -> None:
    if not isinstance(texts, list):
        raise EmbeddingError("texts must be a list of strings")
    for item in texts:
        if not isinstance(item, str):
            raise EmbeddingError("every item in texts must be a string")


def embed_texts(texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]:
    """Embed a batch of texts into BGE-M3 dense vectors (1024 dimensions each).

    Returns [] for an empty input list without invoking the model.

    Args:
        texts: list of strings to embed.
        batch_size: overrides the configured Settings.embedding_batch_size
            for this call, if given.

    Raises:
        EmbeddingError: if texts isn't a list of strings, the model fails
            to load, or embedding generation fails.
    """
    _validate_texts(texts)

    if not texts:
        return []

    settings = Settings.get_instance()
    resolved_batch_size = batch_size if batch_size is not None else settings.embedding_batch_size

    model = _load_model()

    try:
        vectors = model.encode(
            texts,
            batch_size=resolved_batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    except Exception as exc:
        raise EmbeddingError("Failed to generate embeddings") from exc

    embeddings = [vector.tolist() for vector in vectors]

    for embedding in embeddings:
        if len(embedding) != EMBEDDING_DIMENSION:
            raise EmbeddingError(
                f"Embedding model returned dimension {len(embedding)}, "
                f"expected {EMBEDDING_DIMENSION}"
            )

    return embeddings


def embed_text(text: str) -> List[float]:
    """Embed a single text into a BGE-M3 dense vector (1024 dimensions)."""
    if not isinstance(text, str):
        raise EmbeddingError("text must be a string")

    return embed_texts([text])[0]
