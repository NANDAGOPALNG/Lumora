"""ChatService: orchestrates the RAG chat flow.

Wires together, in order

    SearchService -> RagPromptBuilder -> BaseLLMProvider

the components that already exist (SearchService, and the new
RagPromptBuilder / BaseLLMProvider from this task) into a single
`chat()` call.

This service does no retrieval, ranking, context-building, prompt
formatting, or provider-specific generation logic of its own - it only
calls the existing/injected components in sequence and passes each
one's output to the next, exactly the way SearchService orchestrates
the retrieval-stage primitives. In particular, it never touches
Qdrant, PostgreSQL, embeddings, reranking, or the Gemini SDK directly.

Conversation/message persistence is out of scope for this task and is
not implemented here.
"""

from dataclasses import dataclass
from typing import List, Optional

from app.generation.prompt_builder import RagPromptBuilder
from app.llm.base import BaseLLMProvider
from app.retrieval.context_builder import ContextSource
from app.retrieval.validation import DEFAULT_TOP_K, UUIDLike
from app.services.search_service import SearchService


@dataclass
class ChatResult:
    """ChatService's output: the generated answer, the query as
    actually run, and the structured sources the answer was grounded
    in.

    `sources` is exactly `SearchResult.context.sources` - reused
    as-is rather than duplicated into an incompatible shape, since the
    chat response needs to cite the same chunks the search response
    already can.
    """

    answer: str
    query: str
    sources: List[ContextSource]


class ChatService:
    """Thin orchestrator over SearchService, RagPromptBuilder, and a
    BaseLLMProvider.

    Holds only the already-constructed components it's given - it
    creates no database/vector-store/provider connections itself, and
    duplicates no retrieval, prompt-construction, or generation logic.
    Safe to construct once and reuse across multiple chat() calls.

    The `llm_provider` dependency is any `BaseLLMProvider`
    implementation, so a fake/mock provider can be substituted in
    tests without a real Gemini API call.
    """

    def __init__(
        self,
        search_service: SearchService,
        llm_provider: BaseLLMProvider,
        prompt_builder: RagPromptBuilder,
    ):
        self.search_service = search_service
        self.llm_provider = llm_provider
        self.prompt_builder = prompt_builder

    async def chat(
        self,
        query: str,
        workspace_id: UUIDLike,
        *,
        document_id: Optional[UUIDLike] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> ChatResult:
        """Run the full RAG chat flow for `query`, scoped to
        `workspace_id` (and, if given, `document_id`).

        Order of operations:
        1. SearchService runs the existing retrieval pipeline
           (query rewriting, hybrid retrieval, reranking, context
           building) unchanged.
        2. RagPromptBuilder combines the normalized query and the
           built context into a single grounded prompt.
        3. BaseLLMProvider generates an answer for that prompt.

        workspace_id, document_id, and top_k are passed through to
        SearchService unchanged - this method neither widens nor
        re-derives that scope, and performs no additional validation
        of its own beyond what SearchService already does.

        Raises whatever the underlying components raise:
        RetrievalValidationError (and the other exceptions documented
        on SearchService.search) from the retrieval pipeline, or
        LLMConfigurationError / LLMGenerationError / LLMResponseError
        from the LLM provider - none of these are caught or swallowed
        here.
        """
        search_result = await self.search_service.search(
            query,
            workspace_id,
            document_id=document_id,
            top_k=top_k,
        )

        prompt = self.prompt_builder.build_prompt(
            search_result.query.normalized, search_result.context
        )

        answer = await self.llm_provider.generate(prompt)

        return ChatResult(
            answer=answer,
            query=search_result.query.normalized,
            sources=search_result.context.sources,
        )
