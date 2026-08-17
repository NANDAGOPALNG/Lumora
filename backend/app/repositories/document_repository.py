from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.document import Document, DocumentStatus
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Document)

    async def get_by_workspace(self, workspace_id: any) -> List[Document]:
        result = await self.session.execute(
            select(Document).where(Document.workspace_id == workspace_id)
        )
        return result.scalars().all()

    async def get_by_status(self, status: DocumentStatus) -> List[Document]:
        result = await self.session.execute(
            select(Document).where(Document.status == status)
        )
        return result.scalars().all()
