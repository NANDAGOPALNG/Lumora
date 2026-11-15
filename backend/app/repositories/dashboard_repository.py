"""Read-only, user-scoped aggregate queries for the dashboard.

Every query is scoped to `user_id` inside the SQL itself: workspace-owned
records are joined through Workspace and filtered by Workspace.user_id,
conversations are filtered by Conversation.user_id. Nothing here loads
whole tables to count them, and no query selects document content, chunk
text, messages or any connector credential.
"""

from typing import Any, List, Tuple

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector import Connector
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.workspace import Workspace


class DashboardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def count_workspaces(self, user_id: Any) -> int:
        result = await self.session.execute(
            select(func.count(Workspace.id)).where(Workspace.user_id == user_id)
        )
        return int(result.scalar_one())

    async def document_totals(self, user_id: Any) -> Tuple[int, int]:
        """(all documents, chunks of Indexed documents) in one aggregate query."""
        result = await self.session.execute(
            select(
                func.count(Document.id),
                func.coalesce(
                    func.sum(
                        case(
                            (Document.status == DocumentStatus.INDEXED, Document.chunk_count),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .join(Workspace, Workspace.id == Document.workspace_id)
            .where(Workspace.user_id == user_id)
        )
        documents, chunks = result.one()
        return int(documents), int(chunks)

    async def count_conversations(self, user_id: Any) -> int:
        result = await self.session.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        )
        return int(result.scalar_one())

    async def recent_manual_documents(self, user_id: Any, limit: int) -> List[Any]:
        """Latest manually uploaded documents (connector-created ones are
        represented by the connector's own sync entry instead of flooding
        the feed with one row per synced file)."""
        result = await self.session.execute(
            select(
                Document.id,
                Document.filename,
                Document.uploaded_at,
                Document.workspace_id,
                Workspace.name.label("workspace_name"),
            )
            .join(Workspace, Workspace.id == Document.workspace_id)
            .where(Workspace.user_id == user_id, Document.connector_id.is_(None))
            .order_by(Document.uploaded_at.desc(), Document.id)
            .limit(limit)
        )
        return list(result.all())

    async def recent_connector_syncs(self, user_id: Any, limit: int) -> List[Any]:
        result = await self.session.execute(
            select(
                Connector.id,
                Connector.type,
                Connector.connection_name,
                Connector.last_synced,
                Connector.workspace_id,
                Workspace.name.label("workspace_name"),
            )
            .join(Workspace, Workspace.id == Connector.workspace_id)
            .where(Workspace.user_id == user_id, Connector.last_synced.is_not(None))
            .order_by(Connector.last_synced.desc(), Connector.id)
            .limit(limit)
        )
        return list(result.all())

    async def recent_conversations(self, user_id: Any, limit: int) -> List[Any]:
        result = await self.session.execute(
            select(Conversation.id, Conversation.title, Conversation.created_at)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc(), Conversation.id)
            .limit(limit)
        )
        return list(result.all())
