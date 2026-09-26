import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.workspace import Workspace


class DocumentStatus(str, enum.Enum):
    """Document processing lifecycle states, as defined in the DDD."""

    UPLOADED = "Uploaded"
    PROCESSING = "Processing"
    INDEXED = "Indexed"
    FAILED = "Failed"


class Document(Base):
    """A document uploaded to a workspace, pending or completed chunking/indexing.

    `connector_id` is set (non-NULL) for documents created by a connector
    sync (e.g. GitHub, Wave 5C) and NULL for manually uploaded documents.
    It's the authoritative way to scope connector-driven operations
    (reconciling new/changed/deleted files) to only the documents that
    connector actually owns - never another connector's, another
    workspace's, or a manual upload's.

    `source_id` is the stable external identity of this document within
    its connector, when the connector's source system has one that isn't
    safe to conflate with `filename` - added in Wave 6B for Google Drive,
    where a Drive file ID (not the file's name, which can collide or
    change) is that identity, so a connector-scoped source lookup
    (`DocumentRepository.get_by_connector`, filtered by `source_id`) can
    answer "which Document already corresponds to external file X for
    connector Y?" directly, without scanning chunk metadata. GitHub's
    Wave 5C sync predates this field and still uses `filename` (a
    repository path) as its own within-connector identity instead - this
    column is simply unused (NULL) for GitHub and manual documents, and
    the uniqueness of (connector_id, source_id) below only constrains
    connectors that actually populate it.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "uq_documents_connector_source",
            "connector_id",
            "source_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="document_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=DocumentStatus.UPLOADED,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="documents")
    chunks: Mapped[List["Chunk"]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )