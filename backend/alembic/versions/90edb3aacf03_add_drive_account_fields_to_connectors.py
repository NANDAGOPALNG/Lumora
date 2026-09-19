"""add drive_account_email and drive_root_folder_id to connectors

Revision ID: 90edb3aacf03
Revises: 202aceef8756
Create Date: 2026-09-12

Wave 6A: persists the non-secret Google Drive account identity and
optional root-folder scope on the Connector - see
docs/Lumora_LLD.md's Connector Framework section and
app/connectors/google_drive_connector.py for why both are needed
(mirrors github_repo's role for GitHub connectors from Wave 5C: a
server-recorded, API-derived identity, not a client-supplied free-text
label).

Both new columns are nullable, so this is safe to apply against an
existing database: every pre-existing connector row (all GitHub, in
practice, before this wave) simply gets NULL for both, and a Google
Drive connector scoped to the whole Drive rather than one folder also
has a NULL `drive_root_folder_id` going forward.

No credential (access token, refresh token, or client secret) is
stored by this migration or by any column on this table - see
GoogleDriveConnector's and Connector's docstrings.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "90edb3aacf03"
down_revision = "202aceef8756"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "connectors", sa.Column("drive_account_email", sa.String(), nullable=True)
    )
    op.add_column(
        "connectors", sa.Column("drive_root_folder_id", sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("connectors", "drive_root_folder_id")
    op.drop_column("connectors", "drive_account_email")
