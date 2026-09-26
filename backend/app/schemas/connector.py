import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# owner/repo - letters, digits, hyphens, underscores, dots on each side of
# exactly one slash. Rejects obviously malformed input (missing slash,
# empty segments, whitespace) before it's ever sent to GitHub.
_REPO_FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _validate_repo_full_name(value: str) -> str:
    value = value.strip()
    if not _REPO_FULL_NAME_PATTERN.match(value):
        raise ValueError(
            "repo_full_name must be in 'owner/repo' form (e.g. 'octocat/Hello-World')"
        )
    return value


class GitHubConnectorCreate(BaseModel):
    """Request body for POST /api/v1/connectors/github.

    `github_token` is used only to validate access to `repo_full_name`
    at connect time - it is never persisted (the Connector model has
    no credential storage field) and never appears in any response.

    `repo_full_name` is validated here for shape (must look like
    'owner/repo') but the value actually stored on the Connector is
    GitHub's own canonical `full_name` for the repository (returned by
    GitHubConnector.connect()), not this raw client-supplied string -
    see ConnectorService.connect_github.
    """

    workspace_id: UUID = Field(
        ..., description="ID of the workspace to attach this connector to"
    )
    repo_full_name: str = Field(
        ..., description="GitHub repository in 'owner/repo' form, e.g. 'octocat/Hello-World'"
    )
    github_token: str = Field(
        ..., description="GitHub token used to validate access; never stored"
    )
    connection_name: Optional[str] = Field(
        default=None,
        description="Optional display name for this connector; defaults to repo_full_name",
    )

    @field_validator("repo_full_name")
    @classmethod
    def _check_repo_full_name(cls, value: str) -> str:
        return _validate_repo_full_name(value)


class GoogleDriveConnectorCreate(BaseModel):
    """Request body for POST /api/v1/connectors/google-drive.

    `access_token` is a Google Drive OAuth access token, used only to
    validate the connection at connect time - it is never persisted
    (the Connector model has no credential storage field for it,
    mirroring `GitHubConnectorCreate.github_token`) and never appears
    in any response. Obtaining this token (the OAuth consent/callback
    flow itself) is out of scope for this wave - see
    GoogleDriveConnector's module docstring.

    `root_folder_id`, if given, scopes this connector to that single
    Drive folder rather than the whole Drive; it's Drive's own opaque
    file ID for the folder (not a path), validated by
    GoogleDriveConnector.connect().
    """

    workspace_id: UUID = Field(
        ..., description="ID of the workspace to attach this connector to"
    )
    access_token: str = Field(
        ..., description="Google Drive OAuth access token used to validate access; never stored"
    )
    root_folder_id: Optional[str] = Field(
        default=None,
        description="Optional Drive folder ID to scope this connector to; omit for the whole Drive",
    )
    connection_name: Optional[str] = Field(
        default=None,
        description="Optional display name for this connector; defaults to the connected Drive account's email",
    )


class ConnectorResponse(BaseModel):
    """Safe connector metadata - never includes any credential.

    `github_repo` is the server's canonical record of which repository
    this connector syncs (NULL for non-GitHub connectors, and for a
    GitHub connector created before Wave 5C that hasn't been
    reconnected yet) - not sensitive, safe to return.

    `drive_account_email` and `drive_root_folder_id` are the Google
    Drive analogue (Wave 6A) - NULL for non-Google-Drive connectors,
    and `drive_root_folder_id` is also NULL for a Google Drive
    connector scoped to the whole Drive rather than one folder. Never
    an access or refresh token.
    """

    id: UUID
    workspace_id: UUID
    type: str
    connection_name: str
    github_repo: Optional[str] = None
    drive_account_email: Optional[str] = None
    drive_root_folder_id: Optional[str] = None
    last_synced: Optional[datetime] = None
    active: bool

    model_config = ConfigDict(from_attributes=True)


class GitHubSyncRequest(BaseModel):
    """Request body for POST /api/v1/connectors/{connector_id}/sync.

    Wave 5C: no longer accepts `repo_full_name` - the repository to
    sync comes only from the Connector's own stored `github_repo`
    (see ConnectorService.sync_github), so a client can no longer
    substitute a different repository at sync time than the one the
    connector was actually created for.

    `github_token` remains request-provided rather than stored (the
    Connector model has no credential field, by design) and is never
    persisted or included in the response.
    """

    github_token: str = Field(
        ..., description="GitHub token used to authenticate this sync; never stored"
    )


class GitHubSyncResponse(BaseModel):
    """Safe summary of one sync run - never includes any credential."""

    connector_id: UUID
    repository: str
    files_discovered: int
    files_added: int
    files_updated: int
    files_deleted: int
    files_unchanged: int
    files_skipped: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class GoogleDriveSyncRequest(BaseModel):
    """Request body for POST /api/v1/connectors/{connector_id}/sync/google-drive.

    The Drive scope synced always comes from the connector's own stored
    configuration (`drive_root_folder_id`), never a client-supplied
    value - mirroring `GitHubSyncRequest` for the same reason.

    `access_token` remains request-provided rather than stored (the
    Connector model has no credential field, by design) and is never
    persisted or included in the response.
    """

    access_token: str = Field(
        ..., description="Google Drive OAuth access token used to authenticate this sync; never stored"
    )


class GoogleDriveSyncResponse(BaseModel):
    """Safe summary of one Google Drive sync run - never includes any
    credential. Field names mirror `GitHubSyncResponse` where the
    concepts match (Wave 6C added incremental reconciliation -
    additions, updates, and deletions - to what Wave 6B's initial
    version only imported). `notes`, if non-empty, briefly explains
    why individual files were skipped or failed (e.g. an unsupported
    type, or an update that failed and left the previous version
    intact) - never a credential or raw exception detail.
    """

    connector_id: UUID
    files_discovered: int
    files_added: int
    files_updated: int
    files_deleted: int
    files_unchanged: int
    files_skipped: int
    files_failed: int
    status: str
    notes: List[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
