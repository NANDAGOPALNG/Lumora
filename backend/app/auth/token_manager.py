"""
JWT access-token management for Lumora.

Lumora is a stateless, JWT-only architecture: only short-lived access
tokens are issued (see SECRET_KEY / ALGORITHM / ACCESS_TOKEN_EXPIRE_MINUTES
in Settings). No refresh tokens are created and no tokens are persisted.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import UUID

from jose import JWTError, jwt

TOKEN_TYPE_ACCESS = "access"


class TokenManager:
    """Creates and validates JWT access tokens."""

    def __init__(self, secret_key: str, algorithm: str, access_token_expire_minutes: int) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._access_token_expire_minutes = access_token_expire_minutes

    def create_access_token(self, user_id: UUID) -> str:
        """Create a signed JWT access token whose subject is the user's UUID."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self._access_token_expire_minutes)

        payload: Dict[str, Any] = {
            "sub": str(user_id),
            "type": TOKEN_TYPE_ACCESS,
            "iat": now,
            "exp": expires_at,
        }

        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def decode_access_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate a JWT access token.

        Raises:
            ValueError: If the token is expired, malformed, has an invalid
                signature, or is not an access token.
        """
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
        except JWTError as exc:
            raise ValueError(f"Invalid or expired token: {exc}") from exc

        if payload.get("type") != TOKEN_TYPE_ACCESS:
            raise ValueError("Token is not a valid access token")

        if not payload.get("sub"):
            raise ValueError("Token missing subject claim")

        return payload
