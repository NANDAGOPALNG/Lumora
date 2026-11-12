"""Reranking: score (query, chunk) pairs with the Jina AI Reranker API.

Implements only the "Reranker" stage of the larger LLD pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Reranker -> Context Builder

Query rewriting, metadata filtering, context building, and API wiring
are separate stages and are not implemented here. This module is
independent of FastAPI, PostgreSQL, and Qdrant - it only re-scores and
re-sorts an already-retrieved list of HybridSearchResult candidates;
nothing here queries any database or vector store.

No local model is loaded: the FastAPI process only sends text to
Jina and receives relevance scores, so no ML framework is needed.

API: POST https://api.jina.ai/v1/rerank
Model: jina-reranker-v2-base-multilingual (configurable)
"""

import asyncio
import logging
import math
from dataclasses import dataclass
from numbers import Real
from typing import Dict, List, Optional, Sequence
from uuid import UUID

import httpx

from app.config.settings import Settings
from app.retrieval.hybrid_retriever import HybridSearchResult
from app.retrieval.validation import validate_query, validate_top_k

logger = logging.getLogger(__name__)

# Retry configuration for transient errors (HTTP 429, 5xx). Mirrors the
# embedding engine (app/embeddings/engine.py).
_MAX_RETRIES = 3  # total attempts
_BACKOFF_BASE = 1.0  # seconds - doubles on each retry: 1 s, 2 s
_REQUEST_TIMEOUT = 30.0  # seconds


class RerankerError(Exception):
    """Raised when the reranker API fails, returns an invalid response, or
    invalid input is provided. Never carries the API key."""


@dataclass
class RerankedResult:
    """A single reranked hit.

    Field set matches HybridSearchResult (chunk_id, document_id,
    workspace_id, filename, chunk_index, source, content) with `score`
    replaced by the reranker's relevance score for this query -
    the original hybrid RRF score is not preserved here since it's no
    longer meaningful once the results are reranked.
    """

    chunk_id: UUID
    document_id: UUID
    workspace_id: UUID
    filename: str
    chunk_index: int
    source: str
    score: float
    content: Optional[str] = None


def _new_client() -> httpx.AsyncClient:
    """Create the HTTP client for one rerank call (a seam for tests)."""
    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)


async def _sleep(seconds: float) -> None:
    """Backoff sleep (a seam for tests)."""
    await asyncio.sleep(seconds)


def _has_content(candidate: HybridSearchResult) -> bool:
    return candidate.content is not None and candidate.content.strip() != ""


def _to_reranked_result(candidate: HybridSearchResult, score: float) -> RerankedResult:
    return RerankedResult(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        workspace_id=candidate.workspace_id,
        filename=candidate.filename,
        chunk_index=candidate.chunk_index,
        source=candidate.source,
        score=score,
        content=candidate.content,
    )


def _parse_scores(body: object, document_count: int) -> Dict[int, float]:
    """Validate a Jina rerank response and return {document index: score}.

    The API returns results ordered by relevance, not by input position, so
    every score is keyed by the returned `index`. Raises RerankerError unless
    the response contains exactly one finite numeric score for each of the
    `document_count` submitted documents, with no unknown or duplicate index.
    """
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise RerankerError("Jina Reranker API response is missing required fields")

    results = body["results"]
    scores: Dict[int, float] = {}

    for item in results:
        if not isinstance(item, dict) or "index" not in item or "relevance_score" not in item:
            raise RerankerError("Jina Reranker API response is missing required fields")

        index = item["index"]
        score = item["relevance_score"]

        # bool is a subclass of int/Real; reject it explicitly.
        if isinstance(index, bool) or not isinstance(index, int):
            raise RerankerError("Jina Reranker API returned a non-integer result index")
        if index < 0 or index >= document_count:
            raise RerankerError(
                f"Jina Reranker API returned out-of-range result index {index}"
            )
        if index in scores:
            raise RerankerError(
                f"Jina Reranker API returned duplicate result index {index}"
            )
        if isinstance(score, bool) or not isinstance(score, Real) or not math.isfinite(score):
            raise RerankerError("Jina Reranker API returned an invalid relevance score")

        scores[index] = float(score)

    if len(scores) != document_count:
        raise RerankerError(
            f"Jina Reranker API returned {len(scores)} results "
            f"for {document_count} documents"
        )

    return scores


async def _call_jina_api(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    model: str,
    query: str,
    documents: List[str],
) -> Dict[int, float]:
    """POST one rerank request to Jina, with exponential backoff.

    Retries on HTTP 429 (rate-limit) and 5xx (server error). Raises
    RerankerError immediately on timeouts, network errors, any other 4xx
    (including 401/403 auth failures) and malformed responses. Never exposes
    the API key in logs or exception messages.
    """
    # top_n is the full candidate count: every candidate gets a score, and the
    # caller applies top_k itself so ties break deterministically (by chunk_id)
    # rather than by whichever tied document the API happens to return.
    payload = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
        "return_documents": False,
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
            raise RerankerError("Jina Reranker API request timed out") from exc
        except httpx.RequestError as exc:
            raise RerankerError(
                f"Network error calling Jina Reranker API: {type(exc).__name__}"
            ) from exc

        if response.status_code in (401, 403):
            raise RerankerError(
                f"Jina Reranker API authentication failed (HTTP {response.status_code})"
            )

        if response.status_code == 429 or response.status_code >= 500:
            last_error = RerankerError(
                f"Jina Reranker API returned HTTP {response.status_code}"
            )
            if attempt + 1 < _MAX_RETRIES:
                wait = _BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Jina Reranker API returned HTTP %d on attempt %d/%d; "
                    "retrying in %.1f s",
                    response.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                    wait,
                )
                await _sleep(wait)
            continue

        if not response.is_success:
            # Permanent client error (400, 404, 422, ...): retrying won't help.
            raise RerankerError(
                f"Jina Reranker API returned unexpected HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except Exception as exc:
            raise RerankerError("Jina Reranker API returned a malformed response") from exc

        return _parse_scores(body, len(documents))

    raise RerankerError("Jina Reranker API failed after all retries") from last_error


class CrossEncoderReranker:
    """Reranks HybridSearchResult candidates with the Jina Reranker API.

    The class name is kept from the local cross-encoder implementation so
    existing imports and constructors keep working. It holds no state, so it
    is safe to construct once and reuse, or to construct per request.

    `rerank()` is a coroutine: callers must `await` it.
    """

    async def rerank(
        self,
        query: str,
        candidates: Sequence[HybridSearchResult],
        *,
        top_k: Optional[int] = None,
    ) -> List[RerankedResult]:
        """Score each (query, candidate.content) pair with Jina and return
        candidates sorted by relevance score descending (chunk_id ascending
        breaks ties), truncated to top_k if given.

        Candidates whose content is None or blank are never sent to the API.
        Instead of raising or silently dropping them, they're assigned the
        lowest possible score (-inf) and kept at the bottom of the returned
        list, so a caller that only has dense-only hits (no keyword-sourced
        content) still sees them, just deprioritized.

        Returns [] for an empty candidates list, and makes no API request when
        no candidate has content. Raises RetrievalValidationError for an
        invalid query or top_k, and RerankerError if the API key is missing or
        the API call fails or returns an invalid response - none is swallowed.
        """
        validated_query = validate_query(query)

        if not isinstance(candidates, (list, tuple)):
            raise RerankerError("candidates must be a list or tuple of HybridSearchResult")

        resolved_top_k = validate_top_k(top_k) if top_k is not None else None

        if not candidates:
            return []

        scorable: List[HybridSearchResult] = []
        unscorable: List[HybridSearchResult] = []
        for candidate in candidates:
            (scorable if _has_content(candidate) else unscorable).append(candidate)

        scored: List[RerankedResult] = []
        if scorable:
            settings = Settings.get_instance()
            api_key = settings.jina_api_key
            if not api_key:
                raise RerankerError(
                    "JINA_API_KEY is not configured; cannot call the Jina Reranker API"
                )

            async with _new_client() as client:
                scores = await _call_jina_api(
                    client,
                    settings.jina_reranker_url,
                    api_key,
                    settings.jina_reranker_model_name,
                    validated_query,
                    [candidate.content for candidate in scorable],
                )

            # Map by the returned index, never by response position.
            scored = [
                _to_reranked_result(candidate, scores[position])
                for position, candidate in enumerate(scorable)
            ]

        unscored = [_to_reranked_result(candidate, float("-inf")) for candidate in unscorable]

        results = scored + unscored
        results.sort(key=lambda result: (-result.score, str(result.chunk_id)))

        if resolved_top_k is not None:
            results = results[:resolved_top_k]

        return results
