from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GitHubConnectorCreate(BaseModel):
    """Request body for POST /api/v1/connectors/github.

    `github_token` is used only to validate access to `repo_full_name`
    at connect time - it is never persisted (the Connector model has
    no credential storage field) and never appears in any response.
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


class ConnectorResponse(BaseModel):
    """Safe connector metadata - never includes any credential."""

    id: UUID
    workspace_id: UUID
    type: str
    connection_name: str
    last_synced: Optional[datetime] = None
    active: bool

    model_config = ConfigDict(from_attributes=True)


class GitHubSyncRequest(BaseModel):
    """Request body for POST /api/v1/connectors/{connector_id}/sync.

    Both fields are request-provided rather than stored: `github_token`
    because Wave 5A's Connector model has no credential field, and
    `repo_full_name` because the connector's own `connection_name` is a
    free-text display label that may not reliably identify the
    repository - see the Wave 5B report for why this is flagged as a
    Wave 5C architectural item rather than worked around here. Neither
    value is persisted or ever included in the response.
    """

    repo_full_name: str = Field(
        ...,
        description="GitHub repository in 'owner/repo' form; must match this connector's repository",
    )
    github_token: str = Field(
        ..., description="GitHub token used to authenticate this sync; never stored"
    )


class GitHubSyncResponse(BaseModel):
    """Safe summary of one sync run - never includes any credential."""

    connector_id: UUID
    repository: str
    files_discovered: int
    files_indexed: int
    files_skipped: int
    status: str

    model_config = ConfigDict(from_attributes=True)
