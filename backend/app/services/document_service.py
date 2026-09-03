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
from datetime import datetime, timezone

from app.config.settings import Settings
from app.embeddings import embed_texts
from app.ingestion import extract_chunks
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.document import DocumentResponse
from app.storage import local_storage
from app.vector_store import QdrantChunkPoint, QdrantIntegrationError, QdrantVectorStore

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


class IngestionFailedError(Exception):
    """Raised when document parsing/chunking or chunk persistence fails."""


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
    def __init__(
        self,
        document_repository: DocumentRepository,
        workspace_repository: WorkspaceRepository,
        chunk_repository: ChunkRepository,
        vector_store: QdrantVectorStore,
    ):
        self.document_repository = document_repository
        self.workspace_repository = workspace_repository
        self.chunk_repository = chunk_repository
        self.vector_store = vector_store
        self.session = document_repository.session

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
        """Re-run ingestion for a document: parse, chunk, persist Chunk rows,
        embed the new chunks with BGE-M3, and replace the document's vectors
        in Qdrant.

        Returns None if the document doesn't exist or isn't owned by
        user_id (caller should respond 404 without disclosing which).

        Replaces any existing PostgreSQL chunks and Qdrant points rather
        than appending to them. On any failure (parsing/chunking,
        persistence, embedding, or Qdrant indexing), the document is
        marked Failed and IngestionFailedError is raised for the caller
        to turn into an appropriate error response; the document is only
        marked Indexed once both PostgreSQL persistence and Qdrant
        indexing have succeeded.
        """
        document = await self.document_repository.get_by_id_and_workspace_owner(document_id, user_id)
        if document is None:
            return None

        document.status = DocumentStatus.PROCESSING
        await self.session.flush()

        try:
            ingested_chunks = extract_chunks(document.storage_path, document.file_type)

            chunk_rows = [
                Chunk(
                    document_id=document.id,
                    chunk_index=ingested_chunk.index,
                    content=ingested_chunk.text,
                    metadata_=self._build_chunk_metadata(document, ingested_chunk),
                )
                for ingested_chunk in ingested_chunks
            ]

            # A SAVEPOINT: if anything in this block fails, only the chunk
            # delete/insert is rolled back - old chunks are left intact,
            # and the outer transaction (including the Processing status
            # already flushed above) is still usable afterward.
            async with self.session.begin_nested():
                await self.chunk_repository.delete_chunks_for_document(document.id)
                await self.chunk_repository.create_chunks(chunk_rows)

            # create_chunks() flushes the ORM objects above, so each
            # chunk_row.id is now the persisted PostgreSQL UUID - reuse it
            # as the Qdrant point ID rather than generating a new one.
            persisted_count = await self.chunk_repository.count_chunks(document.id)

            # PostgreSQL and Qdrant are two separate systems with no shared
            # transaction. Generate embeddings for the full new chunk set
            # before touching Qdrant at all, so the old (still valid)
            # Qdrant points are never removed unless replacement vectors
            # are actually ready.
            vectors = embed_texts([chunk_row.content for chunk_row in chunk_rows])

            qdrant_points = [
                QdrantChunkPoint(
                    chunk_id=chunk_row.id,
                    document_id=document.id,
                    workspace_id=document.workspace_id,
                    filename=document.filename,
                    chunk_index=chunk_row.chunk_index,
                    source=document.file_type,
                    vector=vector,
                )
                for chunk_row, vector in zip(chunk_rows, vectors)
            ]

            try:
                await self.vector_store.delete_document_chunks(document.id)
                await self.vector_store.upsert_chunks(qdrant_points)
            except QdrantIntegrationError:
                # Best-effort cleanup so a failed reindex doesn't leave a
                # half-written vector set behind. delete_document_chunks
                # only ever removes points for this document_id, so other
                # documents' vectors are never touched. If cleanup itself
                # fails, swallow that failure in favor of re-raising the
                # original error below.
                try:
                    await self.vector_store.delete_document_chunks(document.id)
                except QdrantIntegrationError:
                    pass
                raise

            document.chunk_count = persisted_count
            document.status = DocumentStatus.INDEXED
            await self.session.commit()
        except Exception as exc:
            document.status = DocumentStatus.FAILED
            await self.session.commit()
            raise IngestionFailedError("Document processing failed") from exc

        return DocumentResponse.model_validate(document)

    @staticmethod
    def _build_chunk_metadata(document: Document, ingested_chunk) -> dict:
        metadata = {
            "document_id": str(document.id),
            "workspace_id": str(document.workspace_id),
            "filename": document.filename,
            "chunk_index": ingested_chunk.index,
            "source": document.file_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if ingested_chunk.page_number is not None:
            metadata["page_number"] = ingested_chunk.page_number
        return metadata
