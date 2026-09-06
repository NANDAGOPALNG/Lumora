"""
Chat API routes.

Implements POST /api/v1/chat: the RAG chat flow (SearchService ->
RagPromptBuilder -> GeminiProvider) exposed over HTTP.
GET /chat/history and DELETE /chat/{id} require conversation/message
persistence and are not implemented here (see app/models/conversation.py,
app/models/message.py, which exist but are not yet wired up).

Requires an authenticated user (`get_current_user`). The requested
workspace_id is verified against that user's own workspaces before
being passed to ChatService, using the same WorkspaceRepository lookup
(and the same not-found-rather-than-forbidden convention) as the
search router - this router does not duplicate that authorization
logic, it reuses it exactly as the search router does.

This router only translates HTTP input/output to and from
ChatService, and maps ChatService/provider failures onto HTTP
responses - it performs no retrieval, prompt-construction, or
generation logic of its own.
"""

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.search import SearchSourceResponse
from app.services.chat_service import ChatService
from app.services.search_service import SearchService
from app.vector_store import QdrantVectorStore

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_service(
    session: AsyncSession = Depends(get_db),
    vector_store: QdrantVectorStore = Depends(get_vector_store),
) -> ChatService:
    """Compose ChatService from the existing retrieval primitives plus
    the new generation-layer components.

    Mirrors `get_search_service` (app/api/v1/search/router.py) for the
    retrieval side - the same process-wide QdrantVectorStore singleton
    and per-request AsyncSession, no new database/vector-store
    abstraction - and adds a GeminiProvider and RagPromptBuilder for
    the generation side.
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
    )


def _workspace_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found"},
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
            document_id=payload.document_id,
            top_k=payload.top_k,
        )
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
