"""
Chat API routes.

Implements:
* POST /api/v1/chat - the RAG chat flow (SearchService ->
  RagPromptBuilder -> GeminiProvider), with conversation/message
  persistence.
* GET /api/v1/chat/history - list the current user's conversations,
  newest first.
* GET /api/v1/chat/{conversation_id} - a single conversation and its
  messages, in chronological order.
* DELETE /api/v1/chat/{conversation_id} - delete a conversation (and,
  via the existing DB-level cascade, its messages).

Requires an authenticated user (`get_current_user`). For POST /chat,
the requested workspace_id is verified against that user's own
workspaces before being passed to ChatService, using the same
WorkspaceRepository lookup (and the same not-found-rather-than-
forbidden convention) as the search router - this router does not
duplicate that authorization logic, it reuses it exactly as the
search router does. The history/detail/delete endpoints are
conversation-scoped only (no workspace_id involved), so no workspace
lookup applies to them. `conversation_id` ownership - for all four
endpoints - is verified inside ChatService itself (see
ConversationNotFoundError below), which raises the same single
exception whether a conversation_id doesn't exist at all or belongs to
a different user; this router maps it to the same generic 404 either
way, via `_conversation_not_found()`.

This router only translates HTTP input/output to and from
ChatService, and maps ChatService/provider failures onto HTTP
responses - it performs no retrieval, prompt-construction, generation,
or persistence/query logic of its own.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.document.router import get_vector_store
from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.generation.prompt_builder import RagPromptBuilder
from app.llm.base import (
    LLMConfigurationError,
    LLMGenerationError,
    LLMResponseError,
)
from app.llm.gemini_provider import GeminiProvider
from app.models.user import User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.retrieval import (
    ContextBuilder,
    CrossEncoderReranker,
    DenseRetriever,
    HybridRetriever,
    KeywordRetriever,
    QueryRewriter,
    RetrievalValidationError,
)
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationHistoryResponse,
    ConversationResponse,
    MessageResponse,
)
from app.schemas.search import SearchSourceResponse
from app.services.chat_service import ChatService, ConversationNotFoundError
from app.services.search_service import SearchService
from app.vector_store import QdrantVectorStore

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_service(
    session: AsyncSession = Depends(get_db),
    vector_store: QdrantVectorStore = Depends(get_vector_store),
) -> ChatService:
    """Compose ChatService from the existing retrieval primitives plus
    the generation-layer and persistence-layer components.

    Mirrors `get_search_service` (app/api/v1/search/router.py) for the
    retrieval side - the same process-wide QdrantVectorStore singleton
    and per-request AsyncSession, no new database/vector-store
    abstraction - and adds a GeminiProvider and RagPromptBuilder for
    the generation side, and ConversationRepository/MessageRepository
    (bound to the same request-scoped session) for persistence.
    ChatService itself never constructs a repository or a session.
    """
    dense_retriever = DenseRetriever(vector_store)
    keyword_retriever = KeywordRetriever(session)
    hybrid_retriever = HybridRetriever(dense_retriever, keyword_retriever)

    search_service = SearchService(
        QueryRewriter(),
        hybrid_retriever,
        CrossEncoderReranker(),
        ContextBuilder(),
    )

    return ChatService(
        search_service,
        GeminiProvider(),
        RagPromptBuilder(),
        ConversationRepository(session),
        MessageRepository(session),
    )


def _workspace_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found"},
    )


def _conversation_not_found() -> HTTPException:
    """Same shape/convention as `_workspace_not_found` - a generic 404
    used both when a conversation_id doesn't exist at all and when it
    belongs to a different user, so a request can never distinguish
    the two (see ConversationNotFoundError).
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "CONVERSATION_NOT_FOUND", "message": "Conversation not found"},
    )


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    workspace_repository = WorkspaceRepository(session)
    workspace = await workspace_repository.get_by_id_and_user(
        payload.workspace_id, current_user.id
    )
    if workspace is None:
        raise _workspace_not_found()

    try:
        result = await chat_service.chat(
            payload.query,
            payload.workspace_id,
            current_user.id,
            conversation_id=payload.conversation_id,
            document_id=payload.document_id,
            top_k=payload.top_k,
        )
    except ConversationNotFoundError:
        raise _conversation_not_found()
    except RetrievalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_CHAT_REQUEST", "message": str(exc)},
        )
    except LLMGenerationError as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "TOO_MANY_REQUESTS",
                    "message": "The language model is temporarily rate-limited. Please try again shortly.",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "LLM_GENERATION_FAILED",
                "message": "Failed to generate an answer. Please try again.",
            },
        )
    except (LLMConfigurationError, LLMResponseError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "LLM_GENERATION_FAILED",
                "message": "Failed to generate an answer. Please try again.",
            },
        )

    return ChatResponse(
        answer=result.answer,
        query=result.query,
        conversation_id=result.conversation_id,
        sources=[
            SearchSourceResponse(
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                filename=source.filename,
                source=source.source,
                chunk_index=source.chunk_index,
                score=source.score,
                content=source.content,
            )
            for source in result.sources
        ],
    )


@router.get("/history", response_model=List[ConversationResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> List[ConversationResponse]:
    """List the current user's conversations, newest first.

    Registered before GET /{conversation_id} so the literal "/history"
    path is matched first, rather than being parsed as a
    conversation_id.
    """
    conversations = await chat_service.get_history(current_user.id)
    return [
        ConversationResponse.model_validate(conversation)
        for conversation in conversations
    ]


@router.get("/{conversation_id}", response_model=ConversationHistoryResponse)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> ConversationHistoryResponse:
    """Fetch a single conversation and its messages, in chronological
    order. Returns the generic CONVERSATION_NOT_FOUND 404 both when
    conversation_id doesn't exist and when it belongs to another user.
    """
    try:
        detail = await chat_service.get_conversation(conversation_id, current_user.id)
    except ConversationNotFoundError:
        raise _conversation_not_found()

    return ConversationHistoryResponse(
        id=detail.conversation.id,
        title=detail.conversation.title,
        created_at=detail.conversation.created_at,
        messages=[
            MessageResponse.model_validate(message) for message in detail.messages
        ],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    chat_service: ChatService = Depends(get_chat_service),
) -> Response:
    """Delete a conversation owned by the current user. Its messages
    are removed via the existing Conversation -> Message cascade, not
    by any separate deletion logic here. Returns the generic
    CONVERSATION_NOT_FOUND 404 both when conversation_id doesn't exist
    and when it belongs to another user.
    """
    try:
        await chat_service.delete_conversation(conversation_id, current_user.id)
    except ConversationNotFoundError:
        raise _conversation_not_found()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
