"""add github_repo to connectors and connector_id to documents

Revision ID: 202aceef8756
Revises: 4d1bd179c389
Create Date: 2026-09-08

Wave 5C: persists the non-secret GitHub repository identity
("owner/repo") on the Connector, and scopes documents to the
connector that created them - see docs/Lumora_LLD.md's Connector
Framework section and the Wave 5C report for why both are needed
(connection_name is a free-text display label, not a reliable
repository or ownership identifier).

Both new columns are nullable, so this is safe to apply against an
existing database: every pre-existing connectors/documents row simply
gets NULL for its new column (a pre-existing GitHub connector has no
stored repository until it's reconnected; a pre-existing document is
treated as not connector-owned, i.e. as if manually uploaded, until
it's resynced under the new scheme).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "202aceef8756"
down_revision = "4d1bd179c389"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("connectors", sa.Column("github_repo", sa.String(), nullable=True))

    op.add_column(
        "documents",
        sa.Column(
            "connector_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connectors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_connector_id", "documents", ["connector_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_documents_connector_id", table_name="documents")
    op.drop_column("documents", "connector_id")

    op.drop_column("connectors", "github_repo")
