"""
Document API routes.

Implements POST /api/v1/documents/upload, GET /api/v1/documents,
GET /api/v1/documents/{id}, DELETE /api/v1/documents/{id}, and
POST /api/v1/documents/{id}/reindex, per the API specification.

Every route requires an authenticated user (`get_current_user`), and every
operation is scoped to a workspace owned by that user - a document
belonging to someone else's workspace is never returned, listed,
updated, or deleted, and is treated as not found (404) rather than
forbidden (403), so its existence is never disclosed.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.document import DocumentResponse
from app.services.document_service import (
    DocumentService,
    FileTooLargeError,
    IngestionFailedError,
    UnsupportedFileTypeError,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_service(session: AsyncSession = Depends(get_db)) -> DocumentService:
    return DocumentService(
        DocumentRepository(session),
        WorkspaceRepository(session),
        ChunkRepository(session),
    )


def _document_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
    )


def _workspace_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "WORKSPACE_NOT_FOUND", "message": "Workspace not found"},
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    workspace_id: UUID = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    content = await file.read()

    try:
        document = await document_service.upload_document(
            workspace_id=workspace_id,
            user_id=current_user.id,
            filename=file.filename or "",
            content_type=file.content_type,
            content=content,
        )
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "UNSUPPORTED_FILE_TYPE", "message": str(exc)},
        )
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "FILE_TOO_LARGE", "message": str(exc)},
        )

    if document is None:
        raise _workspace_not_found()

    return document


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> List[DocumentResponse]:
    documents = await document_service.list_documents_for_workspace(workspace_id, current_user.id)
    if documents is None:
        raise _workspace_not_found()
    return documents


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    document = await document_service.get_document_for_user(document_id, current_user.id)
    if document is None:
        raise _document_not_found()
    return document


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> dict:
    deleted = await document_service.delete_document_for_user(document_id, current_user.id)
    if not deleted:
        raise _document_not_found()
    return {"message": "Document deleted successfully"}


@router.post("/{document_id}/reindex", response_model=DocumentResponse)
async def reindex_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    try:
        document = await document_service.reindex_document_for_user(document_id, current_user.id)
    except IngestionFailedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INGESTION_FAILED", "message": "Document processing failed"},
        )
    if document is None:
        raise _document_not_found()
    return document
