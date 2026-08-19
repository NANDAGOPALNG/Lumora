"""
FastAPI dependency providers for authentication.

Wires together the Google OAuth verifier, JWT token manager, and
repositories, and exposes `get_current_user` for retrieving the
authenticated user from a JWT Bearer token.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.auth_service import AuthService
from app.auth.google_oauth_verifier import GoogleOAuthVerifier
from app.auth.token_manager import TokenManager
from app.config.settings import Settings
from app.database.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository

_bearer_scheme = HTTPBearer(auto_error=False)


def get_google_verifier() -> GoogleOAuthVerifier:
    settings = Settings.get_instance()
    return GoogleOAuthVerifier(client_id=settings.google_client_id)


def get_token_manager() -> TokenManager:
    settings = Settings.get_instance()
    return TokenManager(
        secret_key=settings.secret_key,
        algorithm=settings.algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )


def get_auth_service(
    session: AsyncSession = Depends(get_db),
    google_verifier: GoogleOAuthVerifier = Depends(get_google_verifier),
    token_manager: TokenManager = Depends(get_token_manager),
) -> AuthService:
    return AuthService(
        google_verifier=google_verifier,
        token_manager=token_manager,
        user_repository=UserRepository(session),
        workspace_repository=WorkspaceRepository(session),
    )


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
    token_manager: TokenManager = Depends(get_token_manager),
) -> User:
    """Resolve the authenticated user from the request's JWT Bearer token."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing authentication credentials")

    try:
        payload = token_manager.decode_access_token(credentials.credentials)
        user_id = UUID(payload["sub"])
    except (ValueError, KeyError):
        raise _unauthorized("Invalid or expired authentication token")

    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(user_id)

    if user is None:
        raise _unauthorized("User not found")

    return user
