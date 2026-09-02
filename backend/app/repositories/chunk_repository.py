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
