"""ConnectorService: orchestrates connector lifecycle operations.

Wave 5A: creating a GitHub connector (validating workspace ownership,
then validating GitHub access via GitHubConnector, then persisting
the Connector record), listing a workspace's connectors, retrieving
one, and deleting one.

Wave 5B: `sync_github()` - fetching a GitHub repository's supported
files (via GitHubConnector.sync()) and feeding each one through the
*existing* DocumentService pipeline (upload_document ->
reindex_document_for_user - the same two calls an ordinary file
upload goes through). This method contains no chunking, embedding, or
Qdrant logic of its own; it only calls DocumentService, exactly as an
API route would, plus the small amount of orchestration (matching an
already-synced file back to its existing Document row, so re-syncing
doesn't create a duplicate) that doesn't belong inside DocumentService
itself.

Ownership is enforced at the repository/query level throughout (see
ConnectorRepository, WorkspaceRepository) - this service never fetches
a row and checks `.workspace_id`/`.user_id` itself in Python.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from app.config.settings import Settings
from app.connectors.base import ConnectorAuthenticationError, ConnectorResourceNotFoundError
from app.connectors.github_connector import GitHubConnector, GitHubFile
from app.models.connector import Connector
from app.repositories.connector_repository import ConnectorRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.document_service import (
    DocumentService,
    FileTooLargeError,
    IngestionFailedError,
    UnsupportedFileTypeError,
)
from app.storage import local_storage

# Re-exported so callers (the connectors router) can catch GitHub
# credential/repository failures without importing app.connectors.base
# directly - kept here rather than duplicated, since these are the
# same exceptions GitHubConnector.connect() actually raises.
__all__ = [
    "ConnectorService",
    "ConnectorWorkspaceNotFoundError",
    "ConnectorNotFoundError",
    "ConnectorTypeMismatchError",
    "ConnectorAuthenticationError",
    "ConnectorResourceNotFoundError",
    "GitHubSyncSummary",
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


class ConnectorTypeMismatchError(Exception):
    """Raised when an operation for one connector type (e.g. GitHub
    sync) is attempted on a connector of a different type.
    """


@dataclass
class GitHubSyncSummary:
    """The outcome of one `sync_github()` call - safe to return
    directly from the API (see GitHubSyncResponse): no credential, and
    nothing beyond simple counts and identifiers.
    """

    connector_id: UUID
    repository: str
    files_discovered: int
    files_indexed: int
    files_skipped: int
    status: str


class ConnectorService:
    """Thin orchestrator over ConnectorRepository, WorkspaceRepository,
    DocumentService, and a connector implementation (GitHubConnector).

    Holds only the already-constructed repositories/services it's
    given - it creates no database connections itself, and duplicates
    no parsing/chunking/embedding/Qdrant logic (that stays inside
    DocumentService, called here exactly as an API route would call
    it).
    """

    def __init__(
        self,
        connector_repository: ConnectorRepository,
        workspace_repository: WorkspaceRepository,
        document_service: DocumentService,
    ):
        self.connector_repository = connector_repository
        self.workspace_repository = workspace_repository
        self.document_service = document_service

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

    async def sync_github(
        self,
        connector_id: UUID,
        user_id: UUID,
        repo_full_name: str,
        github_token: str,
    ) -> GitHubSyncSummary:
        """Fetch and index every supported file in a GitHub connector's
        repository through the existing DocumentService pipeline, then
        record when this sync happened.

        `repo_full_name` and `github_token` are both request-provided
        for this wave: Wave 5A already established that the token is
        never persisted (Connector has no credential field), and the
        connector's own `connection_name` isn't a reliable place to
        recover the repository identifier either, since a caller may
        have set it to an arbitrary display label at connect time (see
        this method's note in the Wave 5B report on why this is a
        Wave 5C architectural item, not something patched around here).

        Order of operations, matching the existing
        DocumentService.reindex_document_for_user's own all-or-nothing
        approach per file: one failing file (fetch, parse, or index)
        is skipped and counted, never allowed to abort the rest of the
        sync.

        Idempotency: a file already represented by a Document in this
        workspace (matched by filename, which holds the GitHub path)
        has its stored content overwritten and is reindexed under its
        existing document_id, rather than a new Document being
        created - DocumentService.reindex_document_for_user's existing
        replace-not-append chunk/Qdrant logic is what actually keeps
        re-syncing from producing duplicate/stale search results, not
        any new logic here.

        Raises:
            ConnectorNotFoundError: `connector_id` doesn't exist or
                its workspace doesn't belong to `user_id`.
            ConnectorTypeMismatchError: the connector isn't a GitHub
                connector.
            ConnectorAuthenticationError / ConnectorResourceNotFoundError:
                from GitHubConnector.connect(), if `github_token` or
                `repo_full_name` isn't valid/accessible.
        """
        connector = await self.connector_repository.get_by_id_and_workspace_owner(
            connector_id, user_id
        )
        if connector is None:
            raise ConnectorNotFoundError(f"Connector {connector_id} was not found")
        if connector.type != "github":
            raise ConnectorTypeMismatchError(
                f"Connector {connector_id} is not a GitHub connector"
            )

        max_file_size_bytes = Settings.get_instance().max_document_size_bytes
        github_connector = GitHubConnector(
            token=github_token,
            repo_full_name=repo_full_name,
            max_file_size_bytes=max_file_size_bytes,
        )
        # Raises ConnectorAuthenticationError / ConnectorResourceNotFoundError
        # on failure - not caught here, so the router sees them directly,
        # and nothing is persisted/ingested if the repository itself can't
        # be reached at all.
        fetch_result = await github_connector.sync()

        files_indexed = 0
        files_skipped = fetch_result.fetch_failures

        for github_file in fetch_result.files:
            indexed = await self._ingest_github_file(connector, user_id, github_file)
            if indexed:
                files_indexed += 1
            else:
                files_skipped += 1

        connector.last_synced = datetime.now(timezone.utc)
        await self.connector_repository.session.flush()

        return GitHubSyncSummary(
            connector_id=connector.id,
            repository=repo_full_name,
            files_discovered=fetch_result.discovered_count,
            files_indexed=files_indexed,
            files_skipped=files_skipped,
            status="completed",
        )

    async def _ingest_github_file(
        self, connector: Connector, user_id: UUID, github_file: GitHubFile
    ) -> bool:
        """Ingest one already-fetched GitHub file through DocumentService,
        returning True if it was successfully indexed.

        Reuses an existing Document (matched by workspace_id + filename,
        where filename holds the repo-relative path) instead of creating
        a new one when this file was already synced before, by
        overwriting its stored content in place at the same
        storage_path (via the same app.storage.local_storage module
        DocumentService.upload_document already uses) and reindexing
        under the same document_id.
        """
        document_repository = self.document_service.document_repository

        extra_metadata = {
            "origin": "github",
            "connector_id": str(connector.id),
            "repository": github_file.repository,
            "branch": github_file.branch,
            "path": github_file.path,
            "github_url": github_file.url,
            "github_sha": github_file.sha,
        }

        existing = await document_repository.get_by_workspace_and_filename(
            connector.workspace_id, github_file.path
        )

        if existing is not None:
            local_storage.save_file(existing.storage_path, github_file.content)
            await document_repository.update_for_owner(
                existing.id, user_id, {"file_size": len(github_file.content)}
            )
            document_id = existing.id
        else:
            try:
                created = await self.document_service.upload_document(
                    workspace_id=connector.workspace_id,
                    user_id=user_id,
                    filename=github_file.path,
                    content_type=None,
                    content=github_file.content,
                )
            except (UnsupportedFileTypeError, FileTooLargeError):
                return False
            if created is None:
                return False
            document_id = created.id

        try:
            await self.document_service.reindex_document_for_user(
                document_id, user_id, extra_chunk_metadata=extra_metadata
            )
        except IngestionFailedError:
            return False

        return True
