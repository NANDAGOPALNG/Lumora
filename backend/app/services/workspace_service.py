from typing import List, Optional
from uuid import UUID

from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate


class WorkspaceService:
    def __init__(self, workspace_repository: WorkspaceRepository):
        self.workspace_repository = workspace_repository

    async def create_workspace(self, workspace_create: WorkspaceCreate, user_id: UUID) -> WorkspaceResponse:
        from app.models.workspace import Workspace

        workspace_data = workspace_create.model_dump(exclude_unset=True)
        workspace = Workspace(**workspace_data)
        workspace.user_id = user_id

        created_workspace = await self.workspace_repository.create(workspace)

        return WorkspaceResponse.model_validate(created_workspace)

    async def get_workspace_by_id(self, workspace_id: UUID) -> Optional[WorkspaceResponse]:
        workspace = await self.workspace_repository.get_by_id(workspace_id)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def get_workspaces_by_user(self, user_id: UUID) -> List[WorkspaceResponse]:
        workspaces = await self.workspace_repository.get_by_user(user_id)
        return [WorkspaceResponse.model_validate(workspace) for workspace in workspaces]

    async def get_workspace_by_name(self, name: str) -> Optional[WorkspaceResponse]:
        workspace = await self.workspace_repository.get_by_name(name)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def update_workspace(self, workspace_id: UUID, workspace_update: WorkspaceUpdate) -> Optional[WorkspaceResponse]:
        update_data = workspace_update.model_dump(exclude_unset=True)
        workspace = await self.workspace_repository.update(workspace_id, update_data)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def delete_workspace(self, workspace_id: UUID) -> bool:
        return await self.workspace_repository.delete(workspace_id)
