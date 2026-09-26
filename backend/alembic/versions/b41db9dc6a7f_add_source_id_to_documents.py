"""add source_id to documents

Revision ID: b41db9dc6a7f
Revises: 90edb3aacf03
Create Date: 2026-09-19

Wave 6B: persists the stable external identity of a connector-ingested
document (a Google Drive file ID, for the connector type introduced in
this wave) as its own column, rather than relying on `filename` (which
GitHub's existing Wave 5C sync uses as its own within-connector
identity, but which Google Drive file names don't reliably guarantee -
see the Document model's docstring and
app/services/connector_service.py's `sync_google_drive`).

The unique index on (connector_id, source_id) is what Wave 6B's
duplicate-import protection actually relies on - a second ingestion
attempt for the same connector + Drive file ID either finds the
existing Document via this index and skips it, or would otherwise be
rejected by the database constraint itself, rather than depending only
on the service layer to remember to check. `source_id` is nullable and
unindexed beyond this composite index, so this migration doesn't
affect GitHub or manual documents (both leave it NULL, and NULLs don't
collide under Postgres's standard unique-index semantics - see the
Document model's docstring).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b41db9dc6a7f"
down_revision = "90edb3aacf03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("source_id", sa.String(), nullable=True))
    op.create_index(
        "uq_documents_connector_source",
        "documents",
        ["connector_id", "source_id"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_documents_connector_source", table_name="documents")
    op.drop_column("documents", "source_id")
