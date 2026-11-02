from datetime import datetime
from typing import Optional
from uuid import UUID

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


WorkspaceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class WorkspaceCreate(BaseModel):
    name: WorkspaceName = Field(..., description="Workspace name (1-100 characters)")


class WorkspaceUpdate(BaseModel):
    name: Optional[WorkspaceName] = Field(default=None, description="Workspace name (1-100 characters)")

    @field_validator("name")
    @classmethod
    def _name_cannot_be_null(cls, value):
        # Omitting `name` is fine (nothing to update); sending an explicit
        # null would otherwise reach the database as NULL for a NOT NULL column.
        if value is None:
            raise ValueError("name cannot be null")
        return value


class WorkspaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
