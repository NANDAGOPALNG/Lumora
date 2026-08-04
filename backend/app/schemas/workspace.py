from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from typing import Optional
from datetime import datetime

class WorkspaceCreate(BaseModel):
    name: str = Field(..., description="Workspace name")
    description: Optional[str] = Field(default=None, description="Workspace description")

class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, description="Workspace name")
    description: Optional[str] = Field(default=None, description="Workspace description")

class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    owner_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)