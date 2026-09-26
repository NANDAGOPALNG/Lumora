"""ConnectorService: orchestrates connector lifecycle operations.

Wave 5A: creating a GitHub connector (validating workspace ownership,
then validating GitHub access via GitHubConnector, then persisting
the Connector record), listing a workspace's connectors, retrieving
one, and deleting one.

Wave 5B: `sync_github()` - fetching a GitHub repository's supported
files and feeding each one through the *existing* DocumentService
pipeline (upload_document -> reindex_document_for_user - the same two
calls an ordinary file upload goes through).

Wave 5C: `sync_github()` is now incremental and connector-scoped:
- the repository synced is the one stored on the Connector itself
  (`connector.github_repo`), never a client-supplied value (closing
  the repository-confusion gap Wave 5B's report flagged);
- new files are ingested, changed files (by GitHub blob SHA) are
  refetched and reindexed in place, unchanged files are skipped
  without being refetched, and files removed from the repository have
  their corresponding Document (and its chunks/local file/Qdrant
  vectors) removed - all four cases via the existing DocumentService
  pipeline, never a GitHub-specific parallel one.

Wave 6A: `connect_google_drive()` (validating workspace ownership and
Drive access via GoogleDriveConnector, then persisting a Connector
record for that scope) and `discover_google_drive_files()` (listing a
connector's scope, foundation-only - no content fetched).

Wave 6B: `sync_google_drive()` - full (non-incremental) ingestion of a
Google Drive connector's discovered files, feeding each one through
the same *existing* DocumentService pipeline GitHub sync uses
(upload_document -> reindex_document_for_user), with Drive file
identity (`Document.source_id`, not filename - see the Document
model's docstring) as duplicate-import protection. Detecting changes
to an already-imported file and removing Documents for files deleted
from Drive are Wave 6C work, mirroring what Wave 5C added for GitHub.

This service contains no chunking, embedding, Qdrant, or GitHub/Drive
HTTP logic of its own; it only calls
DocumentService/GitHubConnector/GoogleDriveConnector, exactly as an
API route would, plus the small amount of orchestration (matching
discovered files to the Documents this connector already owns) that
doesn't belong inside either of those.

Ownership is enforced at the repository/query level throughout (see
ConnectorRepository, WorkspaceRepository, DocumentRepository) - this
service never fetches a row and checks `.workspace_id`/`.user_id`/
`.connector_id` itself in Python.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from app.config.settings import Settings
from app.connectors.base import ConnectorAuthenticationError, ConnectorResourceNotFoundError
from app.connectors.github_connector import GitHubConnector, GitHubFile
from app.connectors.google_drive_connector import (
    GoogleDriveConnector,
    GoogleDriveFetchedFile,
    GoogleDriveFile,
)
from app.models.connector import Connector
from app.models.document import Document
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
    "ConnectorMissingRepositoryError",
    "ConnectorAuthenticationError",
    "ConnectorResourceNotFoundError",
    "GitHubSyncSummary",
    "GoogleDriveSyncSummary",
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


class ConnectorMissingRepositoryError(Exception):
    """Raised when a GitHub connector has no stored `github_repo` to
    sync - expected only for a connector created before Wave 5C's
    migration (which backfills existing rows with NULL, not a real
    repository); reconnecting recreates the connector with
    `github_repo` populated.
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
    files_added: int
    files_updated: int
    files_deleted: int
    files_unchanged: int
    files_skipped: int
    status: str


@dataclass
class GoogleDriveSyncSummary:
    """The outcome of one `sync_google_drive()` call - safe to return
    directly from the API (see GoogleDriveSyncResponse): no credential,
    and nothing beyond simple counts, identifiers, and short,
    non-secret notes about why individual files were skipped or
    failed.
    """

    connector_id: UUID
    files_discovered: int
    files_imported: int
    files_unchanged: int
    files_skipped: int
    files_failed: int
    status: str
    notes: List[str]


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

        The Connector's `github_repo` (the server's source of truth for
        which repository this connector syncs - see `sync_github`) is
        set from GitHub's own canonical `full_name` for the repository,
        as returned by GitHubConnector.connect() - not the raw,
        possibly differently-cased client input - while
        `connection_name` remains a separate, purely cosmetic display
        label (defaulting to the same canonical name if the caller
        doesn't supply one).

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
        canonical_repo = repo_info["full_name"]

        connector = Connector(
            workspace_id=workspace_id,
            type="github",
            connection_name=connection_name or canonical_repo,
            github_repo=canonical_repo,
            active=True,
        )
        return await self.connector_repository.create(connector)

    async def connect_google_drive(
        self,
        user_id: UUID,
        workspace_id: UUID,
        access_token: str,
        root_folder_id: Optional[str] = None,
        connection_name: Optional[str] = None,
    ) -> Connector:
        """Validate workspace ownership and Google Drive access, then
        create and persist a Connector record for this Drive scope.

        Mirrors `connect_github` above: the Connector's
        `drive_account_email` (and `drive_root_folder_id`, if a folder
        scope was given) is set from Google's own API response (via
        GoogleDriveConnector.connect()), not blindly trusted from
        client input beyond what that call itself validated.
        `connection_name` remains a separate, purely cosmetic display
        label (defaulting to the connected account's email if the
        caller doesn't supply one).

        Raises:
            ConnectorWorkspaceNotFoundError: `workspace_id` doesn't
                exist or doesn't belong to `user_id`.
            ConnectorAuthenticationError: `access_token` is missing,
                invalid, or expired.
            ConnectorResourceNotFoundError: `root_folder_id` was given
                but doesn't exist, isn't accessible with `access_token`,
                or isn't a folder.
        """
        workspace = await self.workspace_repository.get_by_id_and_user(
            workspace_id, user_id
        )
        if workspace is None:
            raise ConnectorWorkspaceNotFoundError(
                f"Workspace {workspace_id} was not found"
            )

        google_drive_connector = GoogleDriveConnector(
            access_token=access_token, root_folder_id=root_folder_id
        )
        # Raises ConnectorAuthenticationError / ConnectorResourceNotFoundError
        # on failure - not caught here, so the router sees them directly.
        connection_info = await google_drive_connector.connect()
        account_email = connection_info["account_email"]
        validated_root_folder_id = connection_info["root_folder_id"]

        connector = Connector(
            workspace_id=workspace_id,
            type="google_drive",
            connection_name=connection_name or account_email or "Google Drive",
            drive_account_email=account_email,
            drive_root_folder_id=validated_root_folder_id,
            active=True,
        )
        return await self.connector_repository.create(connector)

    async def discover_google_drive_files(
        self,
        connector_id: UUID,
        user_id: UUID,
        access_token: str,
    ) -> List[GoogleDriveFile]:
        """List the file/folder metadata directly within an existing
        Google Drive connector's scope - foundation-only discovery, no
        content fetched (see GoogleDriveConnector.discover_files()).

        Not wired to a router endpoint in Wave 6A (the API
        specification's Connector APIs section has no discovery route
        for this wave) - exposed here so Wave 6B's sync can reuse it
        and so it's reachable for testing against a real connector
        row, the same way GitHubConnector.discover_files() existed
        before GitHubConnector.sync() first called it.

        Raises:
            ConnectorNotFoundError: `connector_id` doesn't exist or its
                workspace doesn't belong to `user_id`.
            ConnectorTypeMismatchError: the connector isn't a Google
                Drive connector.
            ConnectorAuthenticationError / ConnectorResourceNotFoundError:
                from GoogleDriveConnector.connect()/discover_files(), if
                `access_token` isn't valid or the stored scope is no
                longer accessible.
        """
        connector = await self.connector_repository.get_by_id_and_workspace_owner(
            connector_id, user_id
        )
        if connector is None:
            raise ConnectorNotFoundError(f"Connector {connector_id} was not found")
        if connector.type != "google_drive":
            raise ConnectorTypeMismatchError(
                f"Connector {connector_id} is not a Google Drive connector"
            )

        google_drive_connector = GoogleDriveConnector(
            access_token=access_token,
            root_folder_id=connector.drive_root_folder_id,
        )
        await google_drive_connector.connect()
        return await google_drive_connector.discover_files()

    async def sync_google_drive(
        self,
        connector_id: UUID,
        user_id: UUID,
        access_token: str,
    ) -> GoogleDriveSyncSummary:
        """Full (non-incremental) ingestion of a Google Drive
        connector's discovered files into Lumora's existing document
        pipeline.

        Wave 6B only: every discovered, supported file not already
        imported for this connector is fetched and ingested; a file
        already imported (matched by `connector_id` + Drive file ID -
        see `Document.source_id`) is left untouched rather than
        refetched/reindexed - detecting and applying *changes* to an
        already-imported file (mirroring GitHub's Wave 5C SHA
        comparison) and removing Documents for files deleted from
        Drive are both Wave 6C work, not this method's.

        `access_token` remains request-provided (mirroring
        `connect_google_drive`) and is never persisted, logged, or
        returned - and never enters Document or chunk metadata either
        (only the Drive file's own non-secret identity/URL does, via
        `_ingest_google_drive_file`).

        Algorithm:
        1. Load the connector, scoped to `user_id`, and confirm it's a
           Google Drive connector.
        2. Authenticate with Drive and discover the connector's scope
           (GoogleDriveConnector.connect() + discover_files()).
        3. Load the Documents this connector already owns
           (DocumentRepository.get_by_connector) and index them by
           `source_id` - never by filename, which Drive doesn't
           guarantee is a stable or unique identity (see the Document
           model's docstring).
        4. For each discovered entry: skip folders; skip a
           Google-native file with no supported export mapping or a
           non-native file of an unsupported type (each noted, not
           silently dropped); skip a file whose Drive file ID already
           has a Document (`files_unchanged`); otherwise fetch and
           ingest it (`files_imported` on success, `files_failed` with
           a note on any fetch/ingest failure - one bad file never
           aborts the rest of the sync).
        5. Update `connector.last_synced` once done.

        If Drive itself can't be authenticated or the connector's
        scope can't be reached at all, nothing is imported and
        `last_synced` is left unchanged - the exception propagates to
        the caller directly, exactly as `connect_google_drive` does.

        Raises:
            ConnectorNotFoundError: `connector_id` doesn't exist or its
                workspace doesn't belong to `user_id`.
            ConnectorTypeMismatchError: the connector isn't a Google
                Drive connector.
            ConnectorAuthenticationError / ConnectorResourceNotFoundError:
                from GoogleDriveConnector.connect()/discover_files(), if
                `access_token` isn't valid or the stored scope is no
                longer accessible.
        """
        connector = await self.connector_repository.get_by_id_and_workspace_owner(
            connector_id, user_id
        )
        if connector is None:
            raise ConnectorNotFoundError(f"Connector {connector_id} was not found")
        if connector.type != "google_drive":
            raise ConnectorTypeMismatchError(
                f"Connector {connector_id} is not a Google Drive connector"
            )

        google_drive_connector = GoogleDriveConnector(
            access_token=access_token,
            root_folder_id=connector.drive_root_folder_id,
        )
        # Raises ConnectorAuthenticationError / ConnectorResourceNotFoundError
        # on failure - not caught here, so nothing is imported and
        # last_synced is left unchanged if Drive can't be reached at all.
        await google_drive_connector.connect()
        discovered = await google_drive_connector.discover_files()

        document_repository = self.document_service.document_repository
        existing_documents = await document_repository.get_by_connector(connector.id)
        existing_by_source_id: Dict[str, Document] = {
            document.source_id: document
            for document in existing_documents
            if document.source_id is not None
        }

        files_imported = 0
        files_unchanged = 0
        files_skipped = 0
        files_failed = 0
        notes: List[str] = []

        for drive_file in discovered:
            if drive_file.is_folder:
                continue

            if drive_file.file_id in existing_by_source_id:
                files_unchanged += 1
                continue

            if not drive_file.is_google_native and drive_file.extension is None:
                files_skipped += 1
                notes.append(f"{drive_file.name}: unsupported file type, skipped")
                continue

            try:
                fetched = await google_drive_connector.fetch_file(drive_file)
            except ConnectorResourceNotFoundError as exc:
                files_skipped += 1
                notes.append(f"{drive_file.name}: {exc}")
                continue

            ingested = await self._ingest_google_drive_file(connector, user_id, fetched)
            if ingested:
                files_imported += 1
            else:
                files_failed += 1
                notes.append(f"{fetched.filename}: ingestion into DocumentService failed")

        connector.last_synced = datetime.now(timezone.utc)
        await self.connector_repository.session.flush()

        return GoogleDriveSyncSummary(
            connector_id=connector.id,
            files_discovered=len(discovered),
            files_imported=files_imported,
            files_unchanged=files_unchanged,
            files_skipped=files_skipped,
            files_failed=files_failed,
            status="completed",
            notes=notes,
        )

    async def _ingest_google_drive_file(
        self,
        connector: Connector,
        user_id: UUID,
        fetched: GoogleDriveFetchedFile,
    ) -> bool:
        """Ingest one already-fetched Google Drive file through
        DocumentService, returning True if it was successfully
        indexed.

        Always creates a new Document (Wave 6B is import-only - a file
        whose Drive file ID already has a Document is filtered out
        before this is called, in `sync_google_drive`), with
        `connector_id` and `source_id` (the Drive file ID) set so a
        later sync can find it via
        DocumentRepository.get_by_connector, and the same Drive source
        metadata (`origin`, `connector_id`, `drive_file_id`, `filename`,
        `drive_url`, `workspace_id`) attached to every one of its
        chunks that GitHub sync attaches for its own source fields
        (Wave 5B/5C) - never the OAuth access token.
        """
        extra_metadata = {
            "origin": "google_drive",
            "connector_id": str(connector.id),
            "drive_file_id": fetched.file_id,
            "filename": fetched.filename,
            "drive_url": fetched.web_view_link,
            "workspace_id": str(connector.workspace_id),
        }

        try:
            created = await self.document_service.upload_document(
                workspace_id=connector.workspace_id,
                user_id=user_id,
                filename=fetched.filename,
                content_type=fetched.mime_type,
                content=fetched.content,
                connector_id=connector.id,
                source_id=fetched.file_id,
            )
        except (UnsupportedFileTypeError, FileTooLargeError):
            return False
        if created is None:
            return False

        try:
            await self.document_service.reindex_document_for_user(
                created.id, user_id, extra_chunk_metadata=extra_metadata
            )
        except IngestionFailedError:
            return False

        return True

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

        Note: this does not delete the connector's previously-synced
        Documents (Document.connector_id is set to NULL via the
        migration's ON DELETE SET NULL, so they simply become
        unowned/orphaned from any connector, like a manual upload) -
        that's an intentional, conservative choice preserved from
        before Wave 5C, out of scope for this wave to change.
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
        github_token: str,
    ) -> GitHubSyncSummary:
        """Incrementally reconcile a GitHub connector's repository
        against Lumora's existing documents for it, through the
        existing DocumentService pipeline.

        The repository synced is always `connector.github_repo` - the
        server's own stored record - never a client-supplied value.
        `github_token` remains request-provided (Wave 5A/5B already
        established the Connector model has no credential field) and
        is never persisted, logged, or returned.

        Algorithm:
        1. Load the connector, scoped to `user_id`, and confirm it's a
           GitHub connector with a stored repository.
        2. Authenticate with GitHub and discover the repository's
           current supported files and their blob SHAs
           (GitHubConnector.sync() - this already both discovers and
           fetches; see the per-file handling below for why an
           unchanged file's already-fetched content is simply
           discarded rather than being fetched separately per file).
        3. Load the Documents this connector already owns
           (DocumentRepository.get_by_connector - never workspace_id +
           filename alone, which can't tell this connector's documents
           apart from another connector's, another repository's, or a
           manual upload's).
        4. For each currently discovered file: if no existing Document
           matches its path, ingest it as new; if one does and its
           stored GitHub SHA differs from the current one, refetch and
           reindex it in place; if the SHA matches, skip it untouched.
        5. For each existing Document owned by this connector whose
           path is no longer discovered, delete it via
           DocumentService.delete_document_for_user - which removes
           its PostgreSQL row (chunks cascade), local file, and Qdrant
           vectors.
        6. Only now, with reconciliation complete, update
           `connector.last_synced`.

        One file's fetch/parse/index failure is counted (files_skipped)
        rather than aborting the rest of the sync, matching Wave 5B's
        existing behavior. If GitHub itself can't be authenticated or
        the repository can't be reached at all, nothing is reconciled
        and `last_synced` is left unchanged - the exception propagates
        to the caller directly.

        Raises:
            ConnectorNotFoundError: `connector_id` doesn't exist or
                its workspace doesn't belong to `user_id`.
            ConnectorTypeMismatchError: the connector isn't a GitHub
                connector.
            ConnectorMissingRepositoryError: the connector has no
                stored `github_repo` (only possible for a connector
                created before Wave 5C - reconnect it).
            ConnectorAuthenticationError / ConnectorResourceNotFoundError:
                from GitHubConnector.connect(), if `github_token` isn't
                valid or the stored repository is no longer accessible.
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
        if not connector.github_repo:
            raise ConnectorMissingRepositoryError(
                f"Connector {connector_id} has no stored repository - reconnect it"
            )

        max_file_size_bytes = Settings.get_instance().max_document_size_bytes
        github_connector = GitHubConnector(
            token=github_token,
            repo_full_name=connector.github_repo,
            max_file_size_bytes=max_file_size_bytes,
        )
        # Raises ConnectorAuthenticationError / ConnectorResourceNotFoundError
        # on failure - not caught here, so the router sees them directly,
        # and nothing is reconciled/last_synced is left unchanged if the
        # repository itself can't be reached at all.
        fetch_result = await github_connector.sync()

        document_repository = self.document_service.document_repository
        existing_documents = await document_repository.get_by_connector(connector.id)
        existing_by_path: Dict[str, Document] = {
            document.filename: document for document in existing_documents
        }

        discovered_paths = set()
        files_added = 0
        files_updated = 0
        files_unchanged = 0
        files_skipped = fetch_result.fetch_failures

        for github_file in fetch_result.files:
            discovered_paths.add(github_file.path)
            existing_document = existing_by_path.get(github_file.path)

            if existing_document is None:
                ingested = await self._ingest_github_file(
                    connector, user_id, github_file, existing_document_id=None
                )
                if ingested:
                    files_added += 1
                else:
                    files_skipped += 1
                continue

            stored_metadata = await self.document_service.chunk_repository.get_metadata_sample(
                existing_document.id
            )
            stored_sha = (stored_metadata or {}).get("github_sha")

            if stored_sha == github_file.sha:
                files_unchanged += 1
                continue

            ingested = await self._ingest_github_file(
                connector, user_id, github_file, existing_document_id=existing_document.id
            )
            if ingested:
                files_updated += 1
            else:
                files_skipped += 1

        files_deleted = 0
        for path, document in existing_by_path.items():
            if path in discovered_paths:
                continue
            deleted = await self.document_service.delete_document_for_user(document.id, user_id)
            if deleted:
                files_deleted += 1

        connector.last_synced = datetime.now(timezone.utc)
        await self.connector_repository.session.flush()

        return GitHubSyncSummary(
            connector_id=connector.id,
            repository=connector.github_repo,
            files_discovered=fetch_result.discovered_count,
            files_added=files_added,
            files_updated=files_updated,
            files_deleted=files_deleted,
            files_unchanged=files_unchanged,
            files_skipped=files_skipped,
            status="completed",
        )

    async def _ingest_github_file(
        self,
        connector: Connector,
        user_id: UUID,
        github_file: GitHubFile,
        *,
        existing_document_id: Optional[UUID],
    ) -> bool:
        """Ingest one already-fetched GitHub file through DocumentService,
        returning True if it was successfully indexed.

        `existing_document_id`, when given, is the Document this
        connector already owns for this path (a changed file - see
        `sync_github`): its stored content is overwritten in place at
        its existing storage_path (via the same app.storage.local_storage
        module DocumentService.upload_document already uses) and it's
        reindexed under the same document_id, rather than a new Document
        being created. When None (a new file), a new Document is created
        via DocumentService.upload_document with `connector_id` set to
        this connector, so future syncs can find it via
        DocumentRepository.get_by_connector.
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

        if existing_document_id is not None:
            existing = await document_repository.get_by_id_and_workspace_owner(
                existing_document_id, user_id
            )
            if existing is None:
                return False
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
                    connector_id=connector.id,
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
