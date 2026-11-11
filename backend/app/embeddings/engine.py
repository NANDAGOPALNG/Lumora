"""Jina AI embedding engine.

Converts text into dense embeddings (1024 dimensions) by calling the
Jina AI Embeddings API asynchronously.  No local model is loaded; the
FastAPI process only sends text and receives float vectors.

API reference: https://api.jina.ai/v1/embeddings
Model: jina-embeddings-v3

Tasks:
  retrieval.passage  – for document chunks at ingestion time
  retrieval.query    – for user search queries at retrieval time
"""

import asyncio
import logging
from typing import List, Optional

import httpx

from app.config.settings import Settings

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSION = 1024

# Retry configuration for transient errors (HTTP 429, 5xx, network issues)
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds – doubles on each retry: 1 s, 2 s, 4 s
_REQUEST_TIMEOUT = 60.0  # seconds


class EmbeddingError(Exception):
    """Raised when embedding generation fails or invalid input is provided."""


def _validate_texts(texts) -> None:
    if not isinstance(texts, list):
        raise EmbeddingError("texts must be a list of strings")
    for item in texts:
        if not isinstance(item, str):
            raise EmbeddingError("every item in texts must be a string")


async def embed_texts(
    texts: List[str],
    task: str = "retrieval.passage",
    batch_size: Optional[int] = None,
) -> List[List[float]]:
    """Embed a batch of texts into Jina AI dense vectors (1024 dimensions each).

    Returns [] for an empty input list without making any API call.

    Args:
        texts:      list of strings to embed.
        task:       Jina task type – ``"retrieval.passage"`` for document
                    chunks, ``"retrieval.query"`` for search queries.
        batch_size: overrides Settings.embedding_batch_size for this call.
                    Large lists are split into multiple API requests of at
                    most this many texts each.

    Raises:
        EmbeddingError: if texts is not a list of strings, the API key is
            missing, authentication fails, the response is malformed, or
            embedding generation fails after all retries.
    """
    _validate_texts(texts)

    if not texts:
        return []

    settings = Settings.get_instance()

    api_key = settings.jina_api_key
    if not api_key:
        raise EmbeddingError(
            "JINA_API_KEY is not configured; cannot call the Jina Embeddings API"
        )

    resolved_batch_size = (
        batch_size if batch_size is not None else settings.embedding_batch_size
    )
    url = settings.jina_embedding_url
    model = settings.embedding_model_name

    # Split into batches to avoid oversized requests
    batches: List[List[str]] = [
        texts[i : i + resolved_batch_size]
        for i in range(0, len(texts), resolved_batch_size)
    ]

    all_embeddings: List[List[float]] = []

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        for batch in batches:
            embedding_batch = await _call_jina_api(
                client, url, api_key, model, task, batch
            )
            all_embeddings.extend(embedding_batch)

    return all_embeddings


async def _call_jina_api(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    model: str,
    task: str,
    batch: List[str],
) -> List[List[float]]:
    """POST one batch to the Jina Embeddings API, with exponential backoff.

    Retries on HTTP 429 (rate-limit) and 5xx (server error).
    Raises EmbeddingError immediately on 401/403 (auth) or malformed response.
    Never exposes the API key in logs or exception messages.
    """
    payload = {
        "model": model,
        "task": task,
        "dimensions": EMBEDDING_DIMENSION,
        "embedding_type": "float",
        "input": batch,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    last_error: Optional[Exception] = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise EmbeddingError(
                "Jina Embeddings API request timed out"
            ) from exc
        except httpx.RequestError as exc:
            raise EmbeddingError(
                f"Network error calling Jina Embeddings API: {type(exc).__name__}"
            ) from exc

        if response.status_code in (401, 403):
            raise EmbeddingError(
                f"Jina Embeddings API authentication failed (HTTP {response.status_code})"
            )

        if response.status_code == 429 or response.status_code >= 500:
            # Transient – back off and retry
            wait = _BACKOFF_BASE * (2**attempt)
            logger.warning(
                "Jina Embeddings API returned HTTP %d on attempt %d/%d; "
                "retrying in %.1f s",
                response.status_code,
                attempt + 1,
                _MAX_RETRIES,
                wait,
            )
            last_error = EmbeddingError(
                f"Jina Embeddings API returned HTTP {response.status_code}"
            )
            await asyncio.sleep(wait)
            continue

        if not response.is_success:
            raise EmbeddingError(
                f"Jina Embeddings API returned unexpected HTTP {response.status_code}"
            )

        # Parse and validate the response
        try:
            body = response.json()
            data = body["data"]
        except Exception as exc:
            raise EmbeddingError(
                "Jina Embeddings API returned a malformed response"
            ) from exc

        # Sort by index to restore the original input order (the API does not
        # guarantee that response items appear in the same order as inputs).
        try:
            data_sorted = sorted(data, key=lambda item: item["index"])
            embeddings = [item["embedding"] for item in data_sorted]
        except (KeyError, TypeError) as exc:
            raise EmbeddingError(
                "Jina Embeddings API response is missing required fields"
            ) from exc

        # Validate every vector dimension
        for i, embedding in enumerate(embeddings):
            if len(embedding) != EMBEDDING_DIMENSION:
                raise EmbeddingError(
                    f"Jina Embeddings API returned dimension {len(embedding)} "
                    f"for item {i}, expected {EMBEDDING_DIMENSION}"
                )

        return embeddings

    # All retries exhausted
    raise EmbeddingError(
        "Jina Embeddings API failed after all retries"
    ) from last_error


async def embed_text(
    text: str,
    task: str = "retrieval.query",
) -> List[float]:
    """Embed a single text into a Jina AI dense vector (1024 dimensions).

    Args:
        text: the string to embed.
        task: Jina task type – defaults to ``"retrieval.query"`` for
              search queries.

    Raises:
        EmbeddingError: if text is not a string or the API call fails.
    """
    if not isinstance(text, str):
        raise EmbeddingError("text must be a string")

    results = await embed_texts([text], task=task)
    return results[0]
