"""
Search API routes.

Implements POST /api/v1/search per the API specification. GET
/search/suggestions is a separate, later feature and is not
implemented here.

Requires an authenticated user (`get_current_user`). The requested
workspace_id is verified against that user's own workspaces before
being passed to SearchService - the retrieval layer trusts whatever
workspace_id it's given (by design; see app/retrieval), so checking
ownership here, at the API boundary, is what keeps a user from
searching a workspace they don't own. A workspace that doesn't belong
to the current user is treated as not found (404), the same
not-found-rather-than-forbidden convention the workspace and document
routers already use.

This router only translates HTTP input/output to and from
SearchService - it performs no retrieval, ranking, or context-building
logic of its own.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.document.router import get_vector_store
from app.auth.dependencies import get_current_user
from app.database.session import get_db
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
from app.schemas.search import SearchRequest, SearchResponse, SearchSourceResponse
from app.services.search_service import SearchService
from app.vector_store import QdrantVectorStore

router = APIRouter(prefix="/search", tags=["search"])


def get_search_service(
    session: AsyncSession = Depends(get_db),
    vector_store: QdrantVectorStore = Depends(get_vector_store),
) -> SearchService:
    """Compose SearchService from the existing retrieval primitives.

    Reuses the same process-wide QdrantVectorStore singleton the
    document router already constructs (via get_vector_store) rather
    than creating a second vector-store instance, and the per-request
    AsyncSession from get_db - no new database/vector-store
    abstraction is introduced here.
    """
    dense_retriever = DenseRetriever(vector_store)
    keyword_retriever = KeywordRetriever(session)
    hybrid_retriever = HybridRetriever(dense_retriever, keyword_retriever)

    return SearchService(
        QueryRewriter(),
        hybrid_retriever,
        CrossEncoderReranker(),
        ContextBuilder(),
    )


def _workspace_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found"},
    )


@router.post("", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    search_service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    workspace_repository = WorkspaceRepository(session)
    workspace = await workspace_repository.get_by_id_and_user(
        payload.workspace_id, current_user.id
    )
    if workspace is None:
        raise _workspace_not_found()

    try:
        result = await search_service.search(
            payload.query,
            payload.workspace_id,
            document_id=payload.document_id,
            top_k=payload.top_k,
        )
    except RetrievalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SEARCH_REQUEST", "message": str(exc)},
        )

    return SearchResponse(
        query=result.query.normalized,
        context=result.context.text,
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
            for source in result.context.sources
        ],
    )