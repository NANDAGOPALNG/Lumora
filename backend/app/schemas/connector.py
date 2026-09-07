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
