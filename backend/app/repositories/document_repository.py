from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.document import Document, DocumentStatus
from app.models.workspace import Workspace
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

    async def get_by_workspace_owner(self, workspace_id: any, user_id: any) -> List[Document]:
        """List documents in workspace_id, but only if that workspace belongs to user_id.

        The ownership check is enforced via a join in the query itself,
        not by fetching documents and checking ownership afterward.
        """
        result = await self.session.execute(
            select(Document)
            .join(Workspace, Document.workspace_id == Workspace.id)
            .where(Document.workspace_id == workspace_id, Workspace.user_id == user_id)
        )
        return result.scalars().all()

    async def get_by_id_and_workspace_owner(self, document_id: any, user_id: any) -> Optional[Document]:
        """Fetch a single document only if its workspace belongs to user_id."""
        result = await self.session.execute(
            select(Document)
            .join(Workspace, Document.workspace_id == Workspace.id)
            .where(Document.id == document_id, Workspace.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_for_owner(self, document_id: any, user_id: any, update_data: dict) -> Optional[Document]:
        """Update a document only if its workspace belongs to user_id."""
        document = await self.get_by_id_and_workspace_owner(document_id, user_id)
        if document is None:
            return None

        for key, value in update_data.items():
            setattr(document, key, value)

        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def delete_for_owner(self, document_id: any, user_id: any) -> Optional[Document]:
        """Delete a document only if its workspace belongs to user_id.

        Returns the deleted document (detached from the session) so the
        caller can still read its `storage_path` to clean up the file on
        disk after the database row is gone.
        """
        document = await self.get_by_id_and_workspace_owner(document_id, user_id)
        if document is None:
            return None

        storage_path = document.storage_path
        await self.session.delete(document)
        await self.session.flush()
        document.storage_path = storage_path
        return document
