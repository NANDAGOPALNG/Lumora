from app.repositories.base import BaseRepository
from app.models.workspace import Workspace
from sqlalchemy.future import select
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

class WorkspaceRepository(BaseRepository[Workspace]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Workspace)

    async def get_by_owner(self, owner_id: any) -> List[Workspace]:
        result = await self.session.execute(
            select(Workspace).where(Workspace.owner_id == owner_id)
        )
        return result.scalars().all()

    async def get_by_name(self, name: str) -> Optional[Workspace]:
        result = await self.session.execute(
            select(Workspace).where(Workspace.name == name)
        )
        return result.scalar_one_or_none()