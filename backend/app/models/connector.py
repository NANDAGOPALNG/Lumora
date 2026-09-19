import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class Connector(Base):
    """An external data-source connection configured for a workspace.

    Supported types (per the DDD): GitHub, Google Drive, Notion.

    `github_repo` stores the canonical, non-secret repository identity
    ("owner/repo") for GitHub connectors - the server's source of truth
    for which repository a sync operates against, independent of
    `connection_name` (a free-text display label that a caller may set
    to anything and that later sync requests must not be trusted to
    resolve back to a real repository). Unused (NULL) for non-GitHub
    connector types.

    `drive_account_email` and `drive_root_folder_id` are the Google
    Drive analogue, added in Wave 6A: the Drive account identity and
    (optional) root folder scope this connector was validated against,
    both returned by Google's API itself (GoogleDriveConnector.connect()),
    not client-supplied free text. Unused (NULL) for non-Google-Drive
    connector types, and `drive_root_folder_id` is also NULL for a
    Google Drive connector scoped to the whole Drive rather than one
    folder.

    Never holds a credential - no column on this model stores an
    access token, refresh token, or client secret for any connector
    type.
    """

    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    connection_name: Mapped[str] = mapped_column(String, nullable=False)
    github_repo: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    drive_account_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    drive_root_folder_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_synced: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="connectors")
