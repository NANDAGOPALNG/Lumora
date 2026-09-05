"""Cross-encoder reranking: score (query, chunk) pairs with a BGE reranker.

Implements only the "Cross-Encoder Reranker" stage of the larger LLD
pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Cross-Encoder Reranker -> Context Builder

Query rewriting, metadata filtering, context building, and API wiring
are separate stages and are not implemented here. This module is
independent of FastAPI, PostgreSQL, and Qdrant - it only re-scores and
re-sorts an already-retrieved list of HybridSearchResult candidates;
nothing here queries any database or vector store, and it isn't wired
into any route yet.
"""

import threading
from dataclasses import dataclass
from typing import List, Optional, Sequence
from uuid import UUID

from app.config.settings import Settings
from app.retrieval.hybrid_retriever import HybridSearchResult
from app.retrieval.validation import validate_query, validate_top_k

_model = None
_model_lock = threading.Lock()


class RerankerError(Exception):
    """Raised when the reranker model fails to load, scoring fails, or
    invalid input is provided."""


@dataclass
class RerankedResult:
    """A single reranked hit.

    Field set matches HybridSearchResult (chunk_id, document_id,
    workspace_id, filename, chunk_index, source, content) with `score`
    replaced by the cross-encoder's relevance score for this query -
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


def _load_model():
    """Lazily load and cache the BGE cross-encoder reranker model.

    Loaded once per process, on first use - not at module import time,
    and not repeated on every rerank() call. Mirrors the embedding
    engine's lazy-singleton pattern (app/embeddings/engine.py).
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
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RerankerError(
                "sentence-transformers is not installed; cannot load the reranker model"
            ) from exc

        settings = Settings.get_instance()

        try:
            loaded_model = CrossEncoder(settings.reranker_model_name)
        except Exception as exc:
            raise RerankerError(
                f"Failed to load reranker model '{settings.reranker_model_name}'"
            ) from exc

        _model = loaded_model

    return _model


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


class CrossEncoderReranker:
    """Reranks HybridSearchResult candidates with a BGE cross-encoder.

    Stateless aside from the lazily-loaded, process-wide model cache -
    safe to construct once and reuse across many rerank() calls, or to
    construct fresh per call; either way the underlying model is
    loaded at most once per process.
    """

    def rerank(
        self,
        query: str,
        candidates: Sequence[HybridSearchResult],
        *,
        top_k: Optional[int] = None,
    ) -> List[RerankedResult]:
        """Score each (query, candidate.content) pair with the cross-encoder
        and return candidates sorted by relevance score descending
        (chunk_id ascending breaks ties), truncated to top_k if given.

        Candidates whose content is None or blank are never passed into
        the model - a cross-encoder can't meaningfully score an empty
        comparison. Instead of raising or silently dropping them, they're
        assigned the lowest possible score (-inf) and kept at the bottom
        of the returned list, so a caller that only has dense-only hits
        (no keyword-sourced content) still sees them, just deprioritized.

        Returns [] for an empty candidates list without loading the
        model. Raises RetrievalValidationError for an invalid query or
        top_k, and RerankerError if the model fails to load or scoring
        itself fails - neither is swallowed.
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

        if scorable:
            model = _load_model()
            pairs = [(validated_query, candidate.content) for candidate in scorable]

            try:
                raw_scores = model.predict(pairs)
            except Exception as exc:
                raise RerankerError("Failed to score candidates with the reranker model") from exc

            scored = [
                _to_reranked_result(candidate, float(raw_score))
                for candidate, raw_score in zip(scorable, raw_scores)
            ]
        else:
            scored = []

        unscored = [_to_reranked_result(candidate, float("-inf")) for candidate in unscorable]

        results = scored + unscored
        results.sort(key=lambda result: (-result.score, str(result.chunk_id)))

        if resolved_top_k is not None:
            results = results[:resolved_top_k]

        return results
