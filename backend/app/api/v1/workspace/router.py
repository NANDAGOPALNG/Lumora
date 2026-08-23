"""
Workspace API routes.

Implements GET /api/v1/workspaces, POST /api/v1/workspaces,
PATCH /api/v1/workspaces/{id}, and DELETE /api/v1/workspaces/{id},
per the API specification.

Every route requires an authenticated user (`get_current_user`), and every
protected operation is scoped to that user's own workspaces at the
repository query level - a workspace owned by someone else is never
returned, updated, or deleted, and is treated as not found (404) rather
than forbidden (403), so its existence is never disclosed.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def get_workspace_service(session: AsyncSession = Depends(get_db)) -> WorkspaceService:
    return WorkspaceService(WorkspaceRepository(session))


def _workspace_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found"},
    )


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> List[WorkspaceResponse]:
    return await workspace_service.get_workspaces_by_user(current_user.id)


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    return await workspace_service.create_workspace(payload, current_user.id)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResponse:
    workspace = await workspace_service.update_workspace_for_user(
        workspace_id, current_user.id, payload
    )
    if workspace is None:
        raise _workspace_not_found()
    return workspace


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> dict:
    deleted = await workspace_service.delete_workspace_for_user(workspace_id, current_user.id)
    if not deleted:
        raise _workspace_not_found()
    return {"message": "Workspace deleted successfully"}
