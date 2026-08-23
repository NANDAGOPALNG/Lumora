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

    async def get_workspaces_by_user(self, user_id: UUID) -> List[WorkspaceResponse]:
        workspaces = await self.workspace_repository.get_by_user(user_id)
        return [WorkspaceResponse.model_validate(workspace) for workspace in workspaces]

    async def get_workspace_by_name(self, name: str) -> Optional[WorkspaceResponse]:
        workspace = await self.workspace_repository.get_by_name(name)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def get_workspace_for_user(self, workspace_id: UUID, user_id: UUID) -> Optional[WorkspaceResponse]:
        """Fetch a single workspace, scoped to its owner.

        Returns None both when the workspace doesn't exist and when it
        belongs to a different user, so callers can't distinguish the two.
        """
        workspace = await self.workspace_repository.get_by_id_and_user(workspace_id, user_id)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def update_workspace_for_user(
        self, workspace_id: UUID, user_id: UUID, workspace_update: WorkspaceUpdate
    ) -> Optional[WorkspaceResponse]:
        """Update a workspace, scoped to its owner.

        Returns None both when the workspace doesn't exist and when it
        belongs to a different user.
        """
        update_data = workspace_update.model_dump(exclude_unset=True)
        workspace = await self.workspace_repository.update_for_owner(workspace_id, user_id, update_data)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def delete_workspace_for_user(self, workspace_id: UUID, user_id: UUID) -> bool:
        """Delete a workspace, scoped to its owner.

        Returns False both when the workspace doesn't exist and when it
        belongs to a different user.
        """
        return await self.workspace_repository.delete_for_owner(workspace_id, user_id)
