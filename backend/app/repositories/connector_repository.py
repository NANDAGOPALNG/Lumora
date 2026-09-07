from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.connector import Connector
from app.models.workspace import Workspace
from app.repositories.base import BaseRepository


class ConnectorRepository(BaseRepository[Connector]):
    """Repository for Connector rows.

    Connector has no `user_id` of its own - ownership lives one level
    up, via `workspace_id` -> `Workspace.user_id` - so every lookup
    that should be scoped to a user enforces that with a join to
    Workspace in the query itself (mirroring
    DocumentRepository.get_by_workspace_owner /
    get_by_id_and_workspace_owner), rather than fetching a row and
    checking ownership in Python afterward.
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, Connector)

    async def get_by_workspace(self, workspace_id: UUID) -> List[Connector]:
        """List connectors in `workspace_id`, without an ownership
        check - use this only when the caller has already verified
        `workspace_id` belongs to the requesting user, otherwise use
        `get_by_workspace_owner`.
        """
        result = await self.session.execute(
            select(Connector).where(Connector.workspace_id == workspace_id)
        )
        return result.scalars().all()

    async def get_by_workspace_owner(
        self, workspace_id: UUID, user_id: UUID
    ) -> List[Connector]:
        """List connectors in `workspace_id`, but only if that
        workspace belongs to `user_id`.

        The ownership check is enforced via a join in the query
        itself, not by fetching connectors and checking ownership
        afterward.
        """
        result = await self.session.execute(
            select(Connector)
            .join(Workspace, Connector.workspace_id == Workspace.id)
            .where(Connector.workspace_id == workspace_id, Workspace.user_id == user_id)
        )
        return result.scalars().all()

    async def get_by_id_and_workspace_owner(
        self, connector_id: UUID, user_id: UUID
    ) -> Optional[Connector]:
        """Fetch a single connector only if its workspace belongs to `user_id`."""
        result = await self.session.execute(
            select(Connector)
            .join(Workspace, Connector.workspace_id == Workspace.id)
            .where(Connector.id == connector_id, Workspace.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_for_owner(
        self, connector_id: UUID, user_id: UUID, update_data: dict
    ) -> Optional[Connector]:
        """Update a connector only if its workspace belongs to `user_id`."""
        connector = await self.get_by_id_and_workspace_owner(connector_id, user_id)
        if connector is None:
            return None

        for key, value in update_data.items():
            setattr(connector, key, value)

        await self.session.flush()
        await self.session.refresh(connector)
        return connector

    async def delete_for_owner(self, connector_id: UUID, user_id: UUID) -> bool:
        """Delete a connector only if its workspace belongs to `user_id`."""
        connector = await self.get_by_id_and_workspace_owner(connector_id, user_id)
        if connector is None:
            return False

        await self.session.delete(connector)
        await self.session.flush()
        return True
