from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentCreate, DocumentUpdate, DocumentResponse
from uuid import UUID
from typing import List, Optional

class DocumentService:
    def __init__(self, document_repository: DocumentRepository):
        self.document_repository = document_repository

    async def create_document(self, document_create: DocumentCreate) -> DocumentResponse:
        # Convert DocumentCreate to Document model
        from app.models.document import Document
        from datetime import datetime

        document_data = document_create.model_dump(exclude_unset=True)
        document = Document(**document_data)

        # Create document through repository
        created_document = await self.document_repository.create(document)

        # Convert to response schema
        return DocumentResponse.model_validate(created_document)

    async def get_document_by_id(self, document_id: UUID) -> Optional[DocumentResponse]:
        document = await self.document_repository.get_by_id(document_id)
        if document:
            return DocumentResponse.model_validate(document)
        return None

    async def get_documents_by_workspace(self, workspace_id: UUID) -> List[DocumentResponse]:
        documents = await self.document_repository.get_by_workspace(workspace_id)
        return [DocumentResponse.model_validate(document) for document in documents]

    async def get_documents_by_creator(self, created_by_id: UUID) -> List[DocumentResponse]:
        documents = await self.document_repository.get_by_creator(created_by_id)
        return [DocumentResponse.model_validate(document) for document in documents]

    async def get_published_documents(self, is_published: bool = True) -> List[DocumentResponse]:
        documents = await self.document_repository.get_published_documents(is_published)
        return [DocumentResponse.model_validate(document) for document in documents]

    async def get_document_by_workspace_and_creator(self, workspace_id: UUID, created_by_id: UUID) -> Optional[DocumentResponse]:
        document = await self.document_repository.get_by_workspace_and_creator(workspace_id, created_by_id)
        if document:
            return DocumentResponse.model_validate(document)
        return None

    async def update_document(self, document_id: UUID, document_update: DocumentUpdate) -> Optional[DocumentResponse]:
        update_data = document_update.model_dump(exclude_unset=True)
        document = await self.document_repository.update(document_id, update_data)
        if document:
            return DocumentResponse.model_validate(document)
        return None

    async def delete_document(self, document_id: UUID) -> bool:
        return await self.document_repository.delete(document_id)