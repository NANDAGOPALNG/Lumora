from typing import List, Optional
from uuid import UUID

from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentCreate, DocumentResponse, DocumentUpdate


class DocumentService:
    def __init__(self, document_repository: DocumentRepository):
        self.document_repository = document_repository

    async def create_document(self, document_create: DocumentCreate) -> DocumentResponse:
        from app.models.document import Document

        document_data = document_create.model_dump(exclude_unset=True)
        document = Document(**document_data)

        created_document = await self.document_repository.create(document)

        return DocumentResponse.model_validate(created_document)

    async def get_document_by_id(self, document_id: UUID) -> Optional[DocumentResponse]:
        document = await self.document_repository.get_by_id(document_id)
        if document:
            return DocumentResponse.model_validate(document)
        return None

    async def get_documents_by_workspace(self, workspace_id: UUID) -> List[DocumentResponse]:
        documents = await self.document_repository.get_by_workspace(workspace_id)
        return [DocumentResponse.model_validate(document) for document in documents]

    async def update_document(self, document_id: UUID, document_update: DocumentUpdate) -> Optional[DocumentResponse]:
        update_data = document_update.model_dump(exclude_unset=True)
        document = await self.document_repository.update(document_id, update_data)
        if document:
            return DocumentResponse.model_validate(document)
        return None

    async def delete_document(self, document_id: UUID) -> bool:
        return await self.document_repository.delete(document_id)
