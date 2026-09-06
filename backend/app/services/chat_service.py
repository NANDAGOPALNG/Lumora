"""ChatService: orchestrates the RAG chat flow.

Wires together, in order

    Conversation lookup/creation -> message history -> SearchService ->
    RagPromptBuilder -> BaseLLMProvider -> message persistence

This service does no retrieval, ranking, context-building, prompt
formatting, provider-specific generation, or raw SQL/session-lifecycle
logic of its own - it only calls the injected repositories/components
in sequence and passes each one's output to the next, exactly the way
SearchService orchestrates the retrieval-stage primitives. In
particular, it never touches Qdrant, PostgreSQL connection/session
setup, embeddings, reranking, or the Gemini SDK directly, and it never
constructs a repository itself - `ConversationRepository` and
`MessageRepository` are injected, already bound to the request-scoped
`AsyncSession` the caller (the chat router) obtained from
`app.database.session.get_db`.

Transaction behavior: this service never calls `session.commit()` -
that happens once, at the end of the request, in `get_db`. Every
write here (`ConversationRepository.create_conversation`,
`MessageRepository.create_message`) only flushes. That means if
anything raises after a write - including the LLM call - the
request's exception propagates out through `get_db`, which rolls the
whole session back, undoing every flushed write from this request
(a newly created conversation included). This is what keeps an
assistant message from ever being persisted without its corresponding
user message, and why both messages are only written after the LLM
call succeeds, not before.
"""

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from app.generation.prompt_builder import ConversationTurn, RagPromptBuilder
from app.llm.base import BaseLLMProvider
from app.models.conversation import Conversation
from app.models.message import Message
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.retrieval.context_builder import ContextSource
from app.retrieval.validation import DEFAULT_TOP_K, UUIDLike
from app.services.search_service import SearchService


class ConversationNotFoundError(Exception):
    """Raised when a supplied conversation_id doesn't exist, or exists
    but doesn't belong to the requesting user.

    Deliberately a single error for both cases - the caller (the chat
    router) must map this to the same generic not-found response
    either way, so a request can never distinguish "no such
    conversation" from "that conversation belongs to someone else".
    """


@dataclass
class ChatResult:
    """ChatService's output: the generated answer, the query as
    actually run, the conversation it was recorded under, and the
    structured sources the answer was grounded in.

    `sources` is exactly `SearchResult.context.sources` - reused
    as-is rather than duplicated into an incompatible shape, since the
    chat response needs to cite the same chunks the search response
    already can.
    """

    answer: str
    query: str
    conversation_id: UUID
    sources: List[ContextSource]


@dataclass
class ConversationDetail:
    """A single conversation plus its messages, in chronological order.

    Both are the raw ORM model instances (`Conversation`, `Message`)
    - as with `ChatResult.sources` above, ChatService hands back
    domain data and leaves building an API response schema to the
    router, rather than importing/depending on `app.schemas` itself.
    """

    conversation: Conversation
    messages: List[Message]


class ChatService:
    """Thin orchestrator over SearchService, RagPromptBuilder, a
    BaseLLMProvider, and the conversation/message repositories.

    Holds only the already-constructed components/repositories it's
    given - it creates no database/vector-store/provider connections
    itself, and duplicates no retrieval, prompt-construction, or
    generation logic. Safe to construct once and reuse across multiple
    chat() calls (the repositories it's given are themselves bound to
    a single request's AsyncSession, so in practice this is
    constructed per-request, same as SearchService).

    The `llm_provider` dependency is any `BaseLLMProvider`
    implementation, and `search_service` can likewise be a fake, so
    ChatService can be exercised in tests without a real Gemini API
    call or a real vector store.
    """

    def __init__(
        self,
        search_service: SearchService,
        llm_provider: BaseLLMProvider,
        prompt_builder: RagPromptBuilder,
        conversation_repository: ConversationRepository,
        message_repository: MessageRepository,
    ):
        self.search_service = search_service
        self.llm_provider = llm_provider
        self.prompt_builder = prompt_builder
        self.conversation_repository = conversation_repository
        self.message_repository = message_repository

    async def chat(
        self,
        query: str,
        workspace_id: UUIDLike,
        user_id: UUID,
        *,
        conversation_id: Optional[UUID] = None,
        document_id: Optional[UUIDLike] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> ChatResult:
        """Run the full RAG chat flow for `query`, scoped to
        `workspace_id` (and, if given, `document_id`), recorded under
        `conversation_id` if given or a newly created conversation
        otherwise.

        Order of operations:
        1. Resolve the conversation: if `conversation_id` is given,
           verify it belongs to `user_id` (raising
           ConversationNotFoundError if not - whether it doesn't
           exist at all or belongs to someone else, the caller can't
           tell which); otherwise create a new conversation owned by
           `user_id`.
        2. Load that conversation's prior messages, if any.
        3. SearchService runs the existing retrieval pipeline (query
           rewriting, hybrid retrieval, reranking, context building)
           unchanged.
        4. RagPromptBuilder combines the prior messages, the current
           RAG context, and the current normalized question into a
           single grounded prompt.
        5. BaseLLMProvider generates an answer for that prompt.
        6. The user's message and the assistant's answer are
           persisted, in that order, only now that generation has
           succeeded.

        workspace_id, document_id, and top_k are passed through to
        SearchService unchanged - this method neither widens nor
        re-derives that scope, and performs no additional retrieval
        validation of its own beyond what SearchService already does.

        Raises:
            ConversationNotFoundError: if `conversation_id` is given
                but doesn't resolve to a conversation owned by
                `user_id`.
            RetrievalValidationError: (and the other exceptions
                documented on SearchService.search) from the retrieval
                pipeline.
            LLMConfigurationError / LLMGenerationError /
                LLMResponseError: from the LLM provider. In every one
                of these cases, no message is persisted - see the
                transaction-behavior note on this module.
        """
        if conversation_id is not None:
            conversation = await self.conversation_repository.get_by_id_and_user(
                conversation_id, user_id
            )
            if conversation is None:
                raise ConversationNotFoundError(
                    f"Conversation {conversation_id} was not found"
                )
            history_messages = await self.message_repository.get_by_conversation(
                conversation.id
            )
        else:
            conversation = await self.conversation_repository.create_conversation(
                user_id
            )
            history_messages = []

        history = [
            ConversationTurn(role=message.role, content=message.content)
            for message in history_messages
        ]

        search_result = await self.search_service.search(
            query,
            workspace_id,
            document_id=document_id,
            top_k=top_k,
        )

        prompt = self.prompt_builder.build_prompt(
            search_result.query.normalized,
            search_result.context,
            history=history or None,
        )

        answer = await self.llm_provider.generate(prompt)

        await self.message_repository.create_message(
            conversation.id, "user", search_result.query.original
        )
        await self.message_repository.create_message(
            conversation.id, "assistant", answer
        )

        return ChatResult(
            answer=answer,
            query=search_result.query.normalized,
            conversation_id=conversation.id,
            sources=search_result.context.sources,
        )

    async def get_history(self, user_id: UUID) -> List[Conversation]:
        """List every conversation belonging to `user_id`, newest first.

        A thin passthrough to `ConversationRepository.get_by_user`,
        which already scopes the query to `user_id` and orders
        newest-first - no additional filtering, sorting, or ownership
        logic is needed or added here.
        """
        return await self.conversation_repository.get_by_user(user_id)

    async def get_conversation(
        self, conversation_id: UUID, user_id: UUID
    ) -> ConversationDetail:
        """Fetch one conversation and its messages, in chronological
        order, scoped to `user_id`.

        Raises ConversationNotFoundError if `conversation_id` doesn't
        exist or doesn't belong to `user_id` - the same check, and the
        same single exception, `chat()` already uses for a supplied
        conversation_id. Messages are only loaded via
        `MessageRepository.get_by_conversation` (not the `_and_user`
        variant) because ownership has already been verified by the
        `get_by_id_and_user` call directly above it.
        """
        conversation = await self.conversation_repository.get_by_id_and_user(
            conversation_id, user_id
        )
        if conversation is None:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} was not found"
            )

        messages = await self.message_repository.get_by_conversation(conversation.id)
        return ConversationDetail(conversation=conversation, messages=messages)

    async def delete_conversation(self, conversation_id: UUID, user_id: UUID) -> None:
        """Delete a conversation, scoped to `user_id`.

        Raises ConversationNotFoundError if `conversation_id` doesn't
        exist or doesn't belong to `user_id`, mirroring `chat()` and
        `get_conversation()` above. The conversation's messages are
        removed via the existing `Conversation` -> `Message` cascade
        (see app/models/conversation.py) - no separate message
        deletion is performed here.
        """
        deleted = await self.conversation_repository.delete_for_owner(
            conversation_id, user_id
        )
        if not deleted:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} was not found"
            )
