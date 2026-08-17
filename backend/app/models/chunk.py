import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import ForeignKey, Index, Integer, JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.document import Document


class Chunk(Base):
    """A chunk of a document's text, mirrored as a point payload in Qdrant."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Mapped as `metadata_` because `metadata` is reserved by SQLAlchemy's
    # Declarative API; the underlying column name is still `metadata`.
    metadata_: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata", JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_metadata_gin", "metadata", postgresql_using="gin"),
    )
