"""
Connector API routes.

Implements, per the API specification's Connector APIs section:
* POST /api/v1/connectors/github - create a GitHub connector for a
  workspace, validating the supplied token and repository first.
* GET /api/v1/connectors - list connectors for a workspace owned by
  the current user (workspace_id is a required query parameter).
* DELETE /api/v1/connectors/{connector_id} - delete a connector owned
  by the current user.
* POST /api/v1/connectors/{connector_id}/sync - fetch and index a
  connected GitHub repository's supported files through the existing
  document ingestion pipeline (Wave 5B).

Google Drive and Notion connectors (also listed in the API
specification) are not implemented in this wave.

Every route requires an authenticated user (`get_current_user`).
Ownership is enforced by ConnectorService/ConnectorRepository at the
query level (see their docstrings) - this router only translates
between HTTP and ConnectorService, and maps
ConnectorWorkspaceNotFoundError / ConnectorNotFoundError /
ConnectorTypeMismatchError / ConnectorAuthenticationError /
ConnectorResourceNotFoundError onto the appropriate HTTP responses. It
performs no database queries, GitHub API calls, or ingestion logic of
its own.

The GitHub token in POST /connectors/github's and
POST /connectors/{id}/sync's request bodies is used only to validate
access / authenticate the sync; it is never persisted, logged, or
included in any response - ConnectorResponse/GitHubSyncResponse expose
only safe metadata.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.document.router import get_vector_store
from app.auth.dependencies import get_current_user
from app.connectors.base import ConnectorAuthenticationError, ConnectorResourceNotFoundError
from app.database.session import get_db
from app.models.user import User
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.connector import (
    ConnectorResponse,
    GitHubConnectorCreate,
    GitHubSyncRequest,
    GitHubSyncResponse,
)
from app.services.connector_service import (
    ConnectorNotFoundError,
    ConnectorService,
    ConnectorTypeMismatchError,
    ConnectorWorkspaceNotFoundError,
)
from app.services.document_service import DocumentService
from app.vector_store import QdrantVectorStore

router = APIRouter(prefix="/connectors", tags=["connectors"])


def get_connector_service(
    session: AsyncSession = Depends(get_db),
    vector_store: QdrantVectorStore = Depends(get_vector_store),
) -> ConnectorService:
    document_service = DocumentService(
        DocumentRepository(session),
        WorkspaceRepository(session),
        ChunkRepository(session),
        vector_store,
    )
    return ConnectorService(
        ConnectorRepository(session), WorkspaceRepository(session), document_service
    )


def _workspace_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found"},
    )


def _connector_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "CONNECTOR_NOT_FOUND", "message": "Connector not found"},
    )


@router.post(
    "/github", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED
)
async def create_github_connector(
    payload: GitHubConnectorCreate,
    current_user: User = Depends(get_current_user),
    connector_service: ConnectorService = Depends(get_connector_service),
) -> ConnectorResponse:
    try:
        connector = await connector_service.connect_github(
            user_id=current_user.id,
            workspace_id=payload.workspace_id,
            repo_full_name=payload.repo_full_name,
            github_token=payload.github_token,
            connection_name=payload.connection_name,
        )
    except ConnectorWorkspaceNotFoundError:
        raise _workspace_not_found()
    except ConnectorAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_GITHUB_CREDENTIALS", "message": str(exc)},
        )
    except ConnectorResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "GITHUB_REPOSITORY_NOT_FOUND", "message": str(exc)},
        )

    return ConnectorResponse.model_validate(connector)


@router.get("", response_model=List[ConnectorResponse])
async def list_connectors(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    connector_service: ConnectorService = Depends(get_connector_service),
) -> List[ConnectorResponse]:
    try:
        connectors = await connector_service.list_connectors_for_workspace(
            workspace_id, current_user.id
        )
    except ConnectorWorkspaceNotFoundError:
        raise _workspace_not_found()

    return [ConnectorResponse.model_validate(connector) for connector in connectors]


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: UUID,
    current_user: User = Depends(get_current_user),
    connector_service: ConnectorService = Depends(get_connector_service),
) -> Response:
    try:
        await connector_service.delete_connector(connector_id, current_user.id)
    except ConnectorNotFoundError:
        raise _connector_not_found()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{connector_id}/sync", response_model=GitHubSyncResponse)
async def sync_github_connector(
    connector_id: UUID,
    payload: GitHubSyncRequest,
    current_user: User = Depends(get_current_user),
    connector_service: ConnectorService = Depends(get_connector_service),
) -> GitHubSyncResponse:
    try:
        summary = await connector_service.sync_github(
            connector_id=connector_id,
            user_id=current_user.id,
            repo_full_name=payload.repo_full_name,
            github_token=payload.github_token,
        )
    except ConnectorNotFoundError:
        raise _connector_not_found()
    except ConnectorTypeMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "UNSUPPORTED_CONNECTOR_TYPE", "message": str(exc)},
        )
    except ConnectorAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_GITHUB_CREDENTIALS", "message": str(exc)},
        )
    except ConnectorResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "GITHUB_REPOSITORY_NOT_FOUND", "message": str(exc)},
        )

    return GitHubSyncResponse.model_validate(summary)
