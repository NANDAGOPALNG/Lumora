from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(..., description="Workspace name")


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, description="Workspace name")


class WorkspaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
