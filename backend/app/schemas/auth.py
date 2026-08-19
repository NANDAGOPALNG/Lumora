from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GoogleAuthRequest(BaseModel):
    google_token: str = Field(..., description="Google OAuth ID token")


class AuthUserSummary(BaseModel):
    """Minimal authenticated-user representation, per the API specification."""

    id: UUID
    name: str
    email: str

    model_config = ConfigDict(from_attributes=True)


class GoogleAuthResponse(BaseModel):
    access_token: str
    user: AuthUserSummary


class LogoutResponse(BaseModel):
    message: str = "Successfully logged out"
