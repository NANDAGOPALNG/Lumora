from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.workspace import Workspace
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Workspace)

    async def get_by_user(self, user_id: any) -> List[Workspace]:
        result = await self.session.execute(
            select(Workspace).where(Workspace.user_id == user_id)
        )
        return result.scalars().all()

    async def get_by_name(self, name: str) -> Optional[Workspace]:
        result = await self.session.execute(
            select(Workspace).where(Workspace.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(self, workspace_id: any, user_id: any) -> Optional[Workspace]:
        """Fetch a workspace only if it belongs to the given user.

        The ownership check is part of the WHERE clause itself, so a
        workspace owned by a different user is never returned.
        """
        result = await self.session.execute(
            select(Workspace).where(
                Workspace.id == workspace_id, Workspace.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def update_for_owner(
        self, workspace_id: any, user_id: any, update_data: dict
    ) -> Optional[Workspace]:
        """Update a workspace only if it belongs to the given user."""
        workspace = await self.get_by_id_and_user(workspace_id, user_id)
        if workspace is None:
            return None

        for key, value in update_data.items():
            setattr(workspace, key, value)

        await self.session.flush()
        await self.session.refresh(workspace)
        return workspace

    async def delete_for_owner(self, workspace_id: any, user_id: any) -> bool:
        """Delete a workspace only if it belongs to the given user."""
        workspace = await self.get_by_id_and_user(workspace_id, user_id)
        if workspace is None:
            return False

        await self.session.delete(workspace)
        await self.session.flush()
        return True
