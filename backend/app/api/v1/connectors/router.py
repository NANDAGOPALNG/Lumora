"""
Connector API routes.

Implements, per the API specification's Connector APIs section:
* POST /api/v1/connectors/github - create a GitHub connector for a
  workspace, validating the supplied token and repository first.
* GET /api/v1/connectors - list connectors for a workspace owned by
  the current user (workspace_id is a required query parameter).
* DELETE /api/v1/connectors/{connector_id} - delete a connector owned
  by the current user.

Google Drive and Notion connectors (also listed in the API
specification) are not implemented in this wave.

Every route requires an authenticated user (`get_current_user`).
Ownership is enforced by ConnectorService/ConnectorRepository at the
query level (see their docstrings) - this router only translates
between HTTP and ConnectorService, and maps
ConnectorWorkspaceNotFoundError / ConnectorNotFoundError /
ConnectorAuthenticationError / ConnectorResourceNotFoundError onto the
appropriate HTTP responses. It performs no database queries or GitHub
API calls of its own.

The GitHub token in POST /connectors/github's request body is used
only to validate access; it is never persisted, logged, or included
in any response - ConnectorResponse exposes only safe metadata (id,
workspace_id, type, connection_name, last_synced, active).
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.connectors.base import ConnectorAuthenticationError, ConnectorResourceNotFoundError
from app.database.session import get_db
from app.models.user import User
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.connector import ConnectorResponse, GitHubConnectorCreate
from app.services.connector_service import (
    ConnectorNotFoundError,
    ConnectorService,
    ConnectorWorkspaceNotFoundError,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


def get_connector_service(session: AsyncSession = Depends(get_db)) -> ConnectorService:
    return ConnectorService(ConnectorRepository(session), WorkspaceRepository(session))


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
