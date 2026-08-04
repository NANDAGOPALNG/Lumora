from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from typing import Optional
from datetime import datetime

class DocumentCreate(BaseModel):
    title: str = Field(..., description="Document title")
    content: Optional[str] = Field(default=None, description="Document content")
    workspace_id: UUID = Field(..., description="ID of the workspace")
    created_by_id: UUID = Field(..., description="ID of the user who created the document")
    is_published: bool = Field(default=False, description="Whether the document is published")
    published_at: Optional[datetime] = Field(default=None, description="Publication timestamp")

class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, description="Document title")
    content: Optional[str] = Field(default=None, description="Document content")
    workspace_id: Optional[UUID] = Field(default=None, description="ID of the workspace")
    created_by_id: Optional[UUID] = Field(default=None, description="ID of the user who created the document")
    is_published: Optional[bool] = Field(default=None, description="Whether the document is published")
    published_at: Optional[datetime] = Field(default=None, description="Publication timestamp")

class DocumentResponse(BaseModel):
    id: UUID
    title: str
    content: Optional[str]
    workspace_id: UUID
    created_by_id: UUID
    is_published: bool
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)