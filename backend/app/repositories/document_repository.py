from app.repositories.base import BaseRepository
from app.models.document import Document
from sqlalchemy.future import select
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_

class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Document)

    async def get_by_workspace(self, workspace_id: any) -> List[Document]:
        result = await self.session.execute(
            select(Document).where(Document.workspace_id == workspace_id)
        )
        return result.scalars().all()

    async def get_by_creator(self, created_by_id: any) -> List[Document]:
        result = await self.session.execute(
            select(Document).where(Document.created_by_id == created_by_id)
        )
        return result.scalars().all()

    async def get_published_documents(self, is_published: bool = True) -> List[Document]:
        result = await self.session.execute(
            select(Document).where(Document.is_published == is_published)
        )
        return result.scalars().all()

    async def get_by_workspace_and_creator(self, workspace_id: any, created_by_id: any) -> Optional[Document]:
        result = await self.session.execute(
            select(Document).where(
                and_(Document.workspace_id == workspace_id, Document.created_by_id == created_by_id)
            )
        )
        return result.scalar_one_or_none()