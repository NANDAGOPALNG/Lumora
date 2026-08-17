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
