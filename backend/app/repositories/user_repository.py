from app.repositories.base import BaseRepository
from app.models.user import User
from sqlalchemy.future import select
from sqlalchemy import and_
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_active_users(self, is_active: bool = True) -> List[User]:
        result = await self.session.execute(
            select(User).where(User.is_active == is_active)
        )
        return result.scalars().all()