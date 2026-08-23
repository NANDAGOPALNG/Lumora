"""
Document service: upload, listing, retrieval, deletion, and reindexing.

Every operation here that touches an existing document or an upload
target is scoped to a workspace owned by the acting user - ownership is
enforced by the repository queries themselves (see DocumentRepository /
WorkspaceRepository), never by fetching a row and comparing ownership
in Python afterward.
"""

from typing import List, Optional
from uuid import UUID, uuid4

from app.config.settings import Settings
from app.models.document import Document, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.document import DocumentResponse
from app.storage import local_storage

ALLOWED_FILE_TYPES = {"pdf", "docx", "txt", "md"}

# Content-types practically observed for each supported extension. Some
# clients (curl, some browsers) send a generic or missing content-type for
# text-like files, so this is a soft check layered on top of the extension
# check, not the sole source of truth.
_ALLOWED_CONTENT_TYPES = {
    "pdf": {"application/pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/x-markdown", "text/plain"},
}

_CONTENT_TYPE_EXEMPTIONS = {"", "application/octet-stream"}


class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file's extension or content-type isn't supported."""


class FileTooLargeError(Exception):
    """Raised when the uploaded file exceeds the configured maximum size."""


def _extract_file_type(filename: str) -> str:
    if not filename or "." not in filename:
        raise UnsupportedFileTypeError(f"File has no extension: {filename!r}")

    extension = filename.rsplit(".", 1)[-1].lower()
    if extension not in ALLOWED_FILE_TYPES:
        raise UnsupportedFileTypeError(f"Unsupported file extension: .{extension}")

    return extension


def _validate_content_type(file_type: str, content_type: Optional[str]) -> None:
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized in _CONTENT_TYPE_EXEMPTIONS:
        return

    allowed = _ALLOWED_CONTENT_TYPES.get(file_type, set())
    if normalized not in allowed:
        raise UnsupportedFileTypeError(
            f"Content-Type '{content_type}' does not match file extension '.{file_type}'"
        )


class DocumentService:
    def __init__(self, document_repository: DocumentRepository, workspace_repository: WorkspaceRepository):
        self.document_repository = document_repository
        self.workspace_repository = workspace_repository

    async def upload_document(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        filename: str,
        content_type: Optional[str],
        content: bytes,
    ) -> Optional[DocumentResponse]:
        """
        Validate, store, and record an uploaded document.

        Returns None if workspace_id doesn't exist or isn't owned by
        user_id (caller should respond 404 without disclosing which).

        Raises:
            UnsupportedFileTypeError: unsupported extension/content-type.
            FileTooLargeError: file exceeds the configured maximum size.
        """
        workspace = await self.workspace_repository.get_by_id_and_user(workspace_id, user_id)
        if workspace is None:
            return None

        file_type = _extract_file_type(filename)
        _validate_content_type(file_type, content_type)

        max_bytes = Settings.get_instance().max_document_size_bytes
        if len(content) > max_bytes:
            raise FileTooLargeError(
                f"File exceeds the maximum allowed size of {max_bytes} bytes"
            )

        document_id = uuid4()
        storage_path = local_storage.generate_storage_path(document_id, file_type)
        local_storage.save_file(storage_path, content)

        try:
            document = Document(
                id=document_id,
                workspace_id=workspace_id,
                filename=filename,
                file_type=file_type,
                file_size=len(content),
                storage_path=storage_path,
                status=DocumentStatus.UPLOADED,
                chunk_count=0,
            )
            created = await self.document_repository.create(document)
        except Exception:
            # Never leave an orphaned file if the DB transaction failed.
            local_storage.delete_file(storage_path)
            raise

        return DocumentResponse.model_validate(created)

    async def list_documents_for_workspace(
        self, workspace_id: UUID, user_id: UUID
    ) -> Optional[List[DocumentResponse]]:
        """Returns None if workspace_id isn't owned by user_id."""
        workspace = await self.workspace_repository.get_by_id_and_user(workspace_id, user_id)
        if workspace is None:
            return None

        documents = await self.document_repository.get_by_workspace_owner(workspace_id, user_id)
        return [DocumentResponse.model_validate(document) for document in documents]

    async def get_document_for_user(self, document_id: UUID, user_id: UUID) -> Optional[DocumentResponse]:
        document = await self.document_repository.get_by_id_and_workspace_owner(document_id, user_id)
        if document:
            return DocumentResponse.model_validate(document)
        return None

    async def delete_document_for_user(self, document_id: UUID, user_id: UUID) -> bool:
        document = await self.document_repository.delete_for_owner(document_id, user_id)
        if document is None:
            return False

        local_storage.delete_file(document.storage_path)
        return True

    async def reindex_document_for_user(self, document_id: UUID, user_id: UUID) -> Optional[DocumentResponse]:
        """Move a document back into Processing with chunk_count reset to 0.

        Does not parse, chunk, embed, or index anything - that's wired up
        in a later task.
        """
        update_data = {"status": DocumentStatus.PROCESSING, "chunk_count": 0}
        document = await self.document_repository.update_for_owner(document_id, user_id, update_data)
        if document:
            return DocumentResponse.model_validate(document)
        return None
