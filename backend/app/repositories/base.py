from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete
from typing import TypeVar, Type, List, Optional, Generic
from app.database.base import Base

T = TypeVar("T", bound=Base)

class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: Type[T]):
        self.session = session
        self.model = model

    async def create(self, obj: T) -> T:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def get_by_id(self, id: any) -> Optional[T]:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        result = await self.session.execute(
            select(self.model).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def update(self, id: any, update_data: dict) -> Optional[T]:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        obj = result.scalar_one_or_none()

        if obj:
            for key, value in update_data.items():
                setattr(obj, key, value)
            await self.session.flush()
            await self.session.refresh(obj)

        return obj

    async def delete(self, id: any) -> bool:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        obj = result.scalar_one_or_none()

        if obj:
            await self.session.delete(obj)
            await self.session.flush()
            return True

        return False