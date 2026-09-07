"""ConnectorService: orchestrates connector lifecycle operations.

Wave 5A scope only: creating a GitHub connector (validating workspace
ownership, then validating GitHub access via GitHubConnector, then
persisting the Connector record), listing a workspace's connectors,
retrieving one, and deleting one. No sync/parse/index (file
fetching/chunking/embedding/Qdrant indexing) happens here - that's
Wave 5B, and belongs to BaseConnector.sync()/parse()/index(), not to
this service.

Ownership is enforced at the repository/query level throughout (see
ConnectorRepository, WorkspaceRepository) - this service never fetches
a row and checks `.workspace_id`/`.user_id` itself in Python.
"""

from typing import List, Optional
from uuid import UUID

from app.connectors.base import ConnectorAuthenticationError, ConnectorResourceNotFoundError
from app.connectors.github_connector import GitHubConnector
from app.models.connector import Connector
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.workspace_repository import WorkspaceRepository

# Re-exported so callers (the connectors router) can catch GitHub
# credential/repository failures without importing app.connectors.base
# directly - kept here rather than duplicated, since these are the
# same exceptions GitHubConnector.connect() actually raises.
__all__ = [
    "ConnectorService",
    "ConnectorWorkspaceNotFoundError",
    "ConnectorNotFoundError",
    "ConnectorAuthenticationError",
    "ConnectorResourceNotFoundError",
]


class ConnectorWorkspaceNotFoundError(Exception):
    """Raised when the supplied workspace_id doesn't exist, or exists
    but doesn't belong to the requesting user.

    A single error for both cases, mirroring the convention already
    used for conversations (see ConversationNotFoundError in
    app/services/chat_service.py) - the caller must map this to the
    same generic not-found response either way.
    """


class ConnectorNotFoundError(Exception):
    """Raised when a supplied connector_id doesn't exist, or exists
    but its workspace doesn't belong to the requesting user. A single
    error for both cases, for the same reason as
    ConnectorWorkspaceNotFoundError above.
    """


class ConnectorService:
    """Thin orchestrator over ConnectorRepository, WorkspaceRepository,
    and a connector implementation (GitHubConnector for Wave 5A).

    Holds only the already-constructed repositories it's given - it
    creates no database connections itself.
    """

    def __init__(
        self,
        connector_repository: ConnectorRepository,
        workspace_repository: WorkspaceRepository,
    ):
        self.connector_repository = connector_repository
        self.workspace_repository = workspace_repository

    async def connect_github(
        self,
        user_id: UUID,
        workspace_id: UUID,
        repo_full_name: str,
        github_token: str,
        connection_name: Optional[str] = None,
    ) -> Connector:
        """Validate workspace ownership and GitHub access, then
        create and persist a Connector record for `repo_full_name`.

        Raises:
            ConnectorWorkspaceNotFoundError: `workspace_id` doesn't
                exist or doesn't belong to `user_id`.
            ConnectorAuthenticationError: `github_token` is missing,
                invalid, or expired.
            ConnectorResourceNotFoundError: `repo_full_name` doesn't
                exist or isn't accessible with `github_token`.
        """
        workspace = await self.workspace_repository.get_by_id_and_user(
            workspace_id, user_id
        )
        if workspace is None:
            raise ConnectorWorkspaceNotFoundError(
                f"Workspace {workspace_id} was not found"
            )

        github_connector = GitHubConnector(
            token=github_token, repo_full_name=repo_full_name
        )
        # Raises ConnectorAuthenticationError / ConnectorResourceNotFoundError
        # on failure - not caught here, so the router sees them directly.
        repo_info = await github_connector.connect()

        connector = Connector(
            workspace_id=workspace_id,
            type="github",
            connection_name=connection_name or repo_info["full_name"],
            active=True,
        )
        return await self.connector_repository.create(connector)

    async def list_connectors_for_workspace(
        self, workspace_id: UUID, user_id: UUID
    ) -> List[Connector]:
        """List connectors in `workspace_id`, scoped to `user_id`.

        Raises ConnectorWorkspaceNotFoundError if `workspace_id`
        doesn't exist or doesn't belong to `user_id`.
        """
        workspace = await self.workspace_repository.get_by_id_and_user(
            workspace_id, user_id
        )
        if workspace is None:
            raise ConnectorWorkspaceNotFoundError(
                f"Workspace {workspace_id} was not found"
            )

        return await self.connector_repository.get_by_workspace_owner(
            workspace_id, user_id
        )

    async def get_connector(self, connector_id: UUID, user_id: UUID) -> Connector:
        """Fetch a single connector, scoped to `user_id`.

        Raises ConnectorNotFoundError if `connector_id` doesn't exist
        or its workspace doesn't belong to `user_id`.
        """
        connector = await self.connector_repository.get_by_id_and_workspace_owner(
            connector_id, user_id
        )
        if connector is None:
            raise ConnectorNotFoundError(f"Connector {connector_id} was not found")
        return connector

    async def delete_connector(self, connector_id: UUID, user_id: UUID) -> None:
        """Delete a connector, scoped to `user_id`.

        Raises ConnectorNotFoundError if `connector_id` doesn't exist
        or its workspace doesn't belong to `user_id`.
        """
        deleted = await self.connector_repository.delete_for_owner(
            connector_id, user_id
        )
        if not deleted:
            raise ConnectorNotFoundError(f"Connector {connector_id} was not found")
