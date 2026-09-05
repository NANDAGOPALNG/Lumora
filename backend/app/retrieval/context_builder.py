"""Context Builder: assemble reranked chunks into structured LLM context.

Implements only the "Context Builder" stage of the larger LLD pipeline

    Query Rewriter -> Embedding Generator -> Hybrid Retriever ->
    Metadata Filter -> Cross-Encoder Reranker -> Context Builder

This is a pure, deterministic transformation over an already-reranked
list of RerankedResult objects - no database, vector store, or LLM
provider is touched here, and no conversation history is included
(that belongs to a later orchestration/chat layer, per the HLD). Not
wired into any API route or SearchService yet.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence
from uuid import UUID

from app.retrieval.reranker import RerankedResult
from app.retrieval.validation import RetrievalValidationError


@dataclass
class ContextSource:
    """Citation metadata for one chunk considered for the built context.

    Included for every input result, regardless of whether it had
    usable content, so a caller can always see what was considered.
    `content` is None when the source chunk's content was missing or
    blank.
    """

    chunk_id: UUID
    document_id: UUID
    filename: str
    source: str
    chunk_index: int
    score: float
    content: Optional[str] = None


@dataclass
class BuiltContext:
    """The Context Builder's output.

    `text` is a single formatted string ready to hand to a future
    LLM/SearchService layer. `sources` is the parallel structured
    citation list, in the same order as the input results, so a caller
    can map a citation marker in `text` (e.g. "[2]") back to its
    metadata via `sources[1]`.
    """

    text: str
    sources: List[ContextSource]


class ContextBuilder:
    """Assembles RerankedResult chunks into a single structured context.

    Stateless - safe to construct once and reuse across many
    build_context() calls, or to construct fresh per call.
    """

    def build_context(self, results: Sequence[RerankedResult]) -> BuiltContext:
        """Combine `results` (already in reranked order) into one context
        string plus a parallel list of source metadata, preserving that
        order throughout.

        Chunks with missing or blank content are excluded from the
        formatted `text` - there's nothing meaningful to include, and
        writing an empty citation block would be malformed - but they
        are still represented in `sources` (with `content=None`), so
        nothing is silently discarded. The result is deterministic:
        the same input always produces the same output.

        Returns BuiltContext(text="", sources=[]) for empty input
        rather than raising. Raises RetrievalValidationError if
        `results` isn't a list/tuple.
        """
        if not isinstance(results, (list, tuple)):
            raise RetrievalValidationError("results must be a list or tuple of RerankedResult")

        if not results:
            return BuiltContext(text="", sources=[])

        sources: List[ContextSource] = []
        text_blocks: List[str] = []

        for position, result in enumerate(results, start=1):
            has_content = result.content is not None and result.content.strip() != ""

            sources.append(
                ContextSource(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    filename=result.filename,
                    source=result.source,
                    chunk_index=result.chunk_index,
                    score=result.score,
                    content=result.content if has_content else None,
                )
            )

            if has_content:
                header = (
                    f"[{position}] {result.filename} "
                    f"(chunk {result.chunk_index}, source: {result.source})"
                )
                text_blocks.append(f"{header}\n{result.content.strip()}")

        text = "\n\n".join(text_blocks)

        return BuiltContext(text=text, sources=sources)
