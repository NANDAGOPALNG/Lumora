from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    email: str = Field(..., description="User's email address (from Google OAuth)")
    username: str = Field(..., description="User's username (from Google OAuth)")
    first_name: Optional[str] = Field(default=None, description="User's first name (from Google OAuth)")
    last_name: Optional[str] = Field(default=None, description="User's last name (from Google OAuth)")
    avatar_url: Optional[str] = Field(default=None, description="URL to user's avatar image (from Google OAuth)")

class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, description="User's username")
    first_name: Optional[str] = Field(default=None, description="User's first name")
    last_name: Optional[str] = Field(default=None, description="User's last name")
    avatar_url: Optional[str] = Field(default=None, description="URL to user's avatar image")

class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_url: Optional[str]
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)