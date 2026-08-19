"""
Google OAuth ID Token verification for Lumora.

Verifies Google-issued ID tokens using the official `google-auth` library
(signature, issuer, audience, and expiration are all validated by
``google.oauth2.id_token.verify_oauth2_token``).
"""

from typing import Any, Dict, Optional

from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config.settings import Settings


class GoogleOAuthVerifier:
    """Verifies Google OAuth ID tokens and extracts user profile information."""

    def __init__(self, client_id: Optional[str] = None) -> None:
        self._client_id = client_id
        self._request = google_requests.Request()

    def verify_id_token(self, id_token: str) -> Dict[str, Any]:
        """
        Verify a Google ID token and extract user profile information.

        Signature, issuer, audience (client ID), and expiration are all
        verified by the underlying google-auth library.

        Args:
            id_token: Google OAuth ID token.

        Returns:
            Dictionary containing the profile data needed by Lumora:
            ``email``, ``name``, and ``picture``.

        Raises:
            ValueError: If token verification fails for any reason, or the
                token does not represent a verified Google account.
        """
        client_id = self._client_id or Settings.get_instance().google_client_id

        try:
            payload = google_id_token.verify_oauth2_token(
                id_token, self._request, client_id
            )
        except (ValueError, google_auth_exceptions.GoogleAuthError) as exc:
            raise ValueError(f"Invalid Google ID token: {exc}") from exc

        if not payload.get("email_verified", False):
            raise ValueError("Google account email is not verified")

        email = payload.get("email")
        if not email:
            raise ValueError("Google token did not include an email address")

        return self._extract_user_profile(payload)

    def _extract_user_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract only the profile fields Lumora needs from the verified token."""
        return {
            "email": payload["email"],
            "name": payload.get("name") or payload["email"],
            "picture": payload.get("picture"),
        }
