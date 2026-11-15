from datetime import datetime, timezone
from typing import List
from uuid import UUID

from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.dashboard import (
    DashboardActivity,
    DashboardStats,
    DashboardSummaryResponse,
)

ACTIVITY_LIMIT = 10
_MAX_TITLE_CHARS = 80

_CONNECTOR_LABELS = {
    "github": "GitHub repository",
    "google_drive": "Google Drive",
    "notion": "Notion",
}


def _aware(value: datetime) -> datetime:
    """Timestamps are timezone-aware in PostgreSQL; SQLite returns naive
    UTC values. Normalise so entries from different tables sort together."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_TITLE_CHARS else text[: _MAX_TITLE_CHARS - 1].rstrip() + "…"


class DashboardService:
    def __init__(self, repository: DashboardRepository):
        self.repository = repository

    async def get_summary(self, user_id: UUID) -> DashboardSummaryResponse:
        workspaces = await self.repository.count_workspaces(user_id)
        documents, indexed_chunks = await self.repository.document_totals(user_id)
        conversations = await self.repository.count_conversations(user_id)

        return DashboardSummaryResponse(
            stats=DashboardStats(
                workspaces=workspaces,
                documents=documents,
                indexed_chunks=indexed_chunks,
                conversations=conversations,
            ),
            recent_activity=await self._recent_activity(user_id),
        )

    async def _recent_activity(self, user_id: UUID) -> List[DashboardActivity]:
        # Each source is limited to ACTIVITY_LIMIT: the overall newest
        # ACTIVITY_LIMIT entries can't include more than that from any one.
        entries: List[DashboardActivity] = []

        for row in await self.repository.recent_manual_documents(user_id, ACTIVITY_LIMIT):
            entries.append(
                DashboardActivity(
                    id=f"document:{row.id}",
                    type="document_uploaded",
                    title=f"Uploaded {_shorten(row.filename)}",
                    description=f"Document added to {_shorten(row.workspace_name)}",
                    created_at=_aware(row.uploaded_at),
                    workspace_id=row.workspace_id,
                    link=f"/workspaces/{row.workspace_id}",
                )
            )

        for row in await self.repository.recent_connector_syncs(user_id, ACTIVITY_LIMIT):
            label = _CONNECTOR_LABELS.get(row.type, "Connector")
            entries.append(
                DashboardActivity(
                    id=f"connector:{row.id}",
                    type="connector_synced",
                    title=f"Synced {_shorten(row.connection_name)}",
                    description=f"{label} synced in {_shorten(row.workspace_name)}",
                    created_at=_aware(row.last_synced),
                    workspace_id=row.workspace_id,
                    link="/integrations",
                )
            )

        for row in await self.repository.recent_conversations(user_id, ACTIVITY_LIMIT):
            title = _shorten(row.title) if row.title and row.title.strip() else "Untitled conversation"
            entries.append(
                DashboardActivity(
                    id=f"conversation:{row.id}",
                    type="conversation_created",
                    title=f"Started conversation: {title}",
                    description="New chat with your knowledge base",
                    created_at=_aware(row.created_at),
                    workspace_id=None,
                    link=f"/chat?c={row.id}",
                )
            )

        entries.sort(key=lambda entry: (entry.created_at, entry.id), reverse=True)
        return entries[:ACTIVITY_LIMIT]
