"""
Authentication API routes.

Implements POST /api/v1/auth/google, GET /api/v1/auth/me, and
POST /api/v1/auth/logout, per the API specification.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.auth_service import AuthService
from app.auth.dependencies import get_auth_service, get_current_user
from app.models.user import User
from app.schemas.auth import (
    AuthUserSummary,
    GoogleAuthRequest,
    GoogleAuthResponse,
    LogoutResponse,
)
from app.schemas.user import UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=GoogleAuthResponse)
async def login_with_google(
    payload: GoogleAuthRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> GoogleAuthResponse:
    try:
        result = await auth_service.authenticate_with_google(payload.google_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_GOOGLE_TOKEN",
                "message": "Google authentication failed",
            },
        )

    return GoogleAuthResponse(
        access_token=result.access_token,
        user=AuthUserSummary.model_validate(result.user),
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    current_user: User = Depends(get_current_user),
) -> LogoutResponse:
    # Lumora's JWT architecture is stateless: there is no server-side
    # session or token store to invalidate. Successfully resolving the
    # current user from the Bearer token confirms the session is valid;
    # actual token removal is handled client-side.
    return LogoutResponse()
