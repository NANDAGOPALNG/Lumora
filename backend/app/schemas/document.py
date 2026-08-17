from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus


class DocumentCreate(BaseModel):
    workspace_id: UUID = Field(..., description="ID of the workspace this document belongs to")
    filename: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="File type/extension, e.g. 'pdf'")
    file_size: int = Field(..., description="File size in bytes")
    storage_path: str = Field(..., description="Path/key where the file is stored")


class DocumentUpdate(BaseModel):
    status: Optional[DocumentStatus] = Field(default=None, description="Processing status")
    chunk_count: Optional[int] = Field(default=None, description="Number of chunks produced")


class DocumentResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    filename: str
    file_type: str
    file_size: int
    storage_path: str
    status: DocumentStatus
    chunk_count: int
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)
