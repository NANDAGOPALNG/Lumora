"""
Authentication service for Lumora.

Implements the Google OAuth sign-in flow: verifies a Google ID token,
finds or provisions the corresponding user (creating a personal
workspace on first login), and issues a JWT access token.
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.auth.google_oauth_verifier import GoogleOAuthVerifier
from app.auth.token_manager import TokenManager
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository

PERSONAL_WORKSPACE_NAME = "Personal Workspace"


@dataclass
class AuthResult:
    """Result of a successful authentication: an access token plus the user."""

    access_token: str
    user: User


class AuthService:
    """Handles Google OAuth authentication and JWT issuance."""

    def __init__(
        self,
        google_verifier: GoogleOAuthVerifier,
        token_manager: TokenManager,
        user_repository: UserRepository,
        workspace_repository: WorkspaceRepository,
    ) -> None:
        self._google_verifier = google_verifier
        self._token_manager = token_manager
        self._user_repository = user_repository
        self._workspace_repository = workspace_repository

    async def authenticate_with_google(self, google_token: str) -> AuthResult:
        """
        Verify a Google ID token and return an authenticated session.

        Raises:
            ValueError: If the Google ID token is invalid.
        """
        profile = self._google_verifier.verify_id_token(google_token)

        email = profile["email"]
        name = profile["name"]
        picture = profile.get("picture")

        user = await self._user_repository.get_by_email(email)

        if user is None:
            user = await self._create_user(email=email, name=name, picture=picture)
            await self._create_personal_workspace(user.id)
        else:
            user = await self._sync_profile(user, name=name, picture=picture)

        access_token = self._token_manager.create_access_token(user.id)

        return AuthResult(access_token=access_token, user=user)

    async def _create_user(self, email: str, name: str, picture: Optional[str]) -> User:
        user = User(email=email, name=name, picture_url=picture)
        return await self._user_repository.create(user)

    async def _create_personal_workspace(self, user_id: UUID) -> None:
        workspace = Workspace(user_id=user_id, name=PERSONAL_WORKSPACE_NAME)
        await self._workspace_repository.create(workspace)

    async def _sync_profile(self, user: User, name: str, picture: Optional[str]) -> User:
        """Update profile fields from verified Google data only when they've changed."""
        update_data = {}

        if name and user.name != name:
            update_data["name"] = name
        if picture and user.picture_url != picture:
            update_data["picture_url"] = picture

        if not update_data:
            return user

        updated_user = await self._user_repository.update(user.id, update_data)
        return updated_user or user
