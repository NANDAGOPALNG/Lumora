from typing import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk


class ChunkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def delete_chunks_for_document(self, document_id: UUID) -> None:
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document_id))

    async def create_chunks(self, chunks: Sequence[Chunk]) -> None:
        """Bulk-insert chunks in a single flush rather than one insert per chunk."""
        if not chunks:
            return
        self.session.add_all(chunks)
        await self.session.flush()

    async def count_chunks(self, document_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        )
        return result.scalar_one()

    async def get_metadata_sample(self, document_id: UUID):
        """Return one chunk's metadata dict for document_id, or None if
        it currently has no chunks.

        Every chunk of a single document shares the same document-level
        metadata fields (filename, source, and - for GitHub-sourced
        documents - github_sha; see
        DocumentService._build_chunk_metadata), so one chunk is enough.
        Used by GitHub incremental sync (Wave 5C) to compare a
        previously-indexed file's stored SHA against the current one
        without needing to load every chunk.
        """
        result = await self.session.execute(
            select(Chunk.metadata_).where(Chunk.document_id == document_id).limit(1)
        )
        row = result.first()
        return row[0] if row else None
