from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    email: str = Field(..., description="User's email address (from Google OAuth)")
    name: str = Field(..., description="User's display name (from Google OAuth)")
    picture_url: Optional[str] = Field(default=None, description="URL to user's profile picture (from Google OAuth)")


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, description="User's display name")
    picture_url: Optional[str] = Field(default=None, description="URL to user's profile picture")


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    picture_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
