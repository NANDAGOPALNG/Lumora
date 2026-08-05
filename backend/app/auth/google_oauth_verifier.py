"""
Google OAuth ID Token verification for Lumora.

This module provides Google OAuth ID token verification functionality.
"""
# TODO:
# Replace manual verification with the official google-auth library
# before production deployment.

import json
import urllib.request
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from jose import jwt
from app.config.settings import Settings

class GoogleOAuthVerifier:
    """Verifies Google OAuth ID tokens and extracts user profile information."""

    # Google OAuth endpoints and constants
    GOOGLE_WELL_KNOWN_KEYS_URL = "https://www.googleapis.com/oauth2/v1/certs"

    def verify_id_token(self, id_token: str, client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Verify a Google ID token and extract user profile information.

        Args:
            id_token: Google OAuth ID token
            client_id: Expected client ID (defaults to configured client ID)

        Returns:
            Dictionary containing verified Google profile information

        Raises:
            ValueError: If token verification fails for any reason
        """
        # Get configured client ID if not provided
        if client_id is None:
            settings = Settings.get_instance()
            client_id = settings.google_client_id

        # Decode token without verification to get payload
        try:
            payload = jwt.decode(
                id_token,
                options={"verify_signature": False, "verify_aud": False}
            )
        except Exception as e:
            raise ValueError(f"Invalid token format: {str(e)}")

        # Validate required fields
        self._validate_token_payload(payload)

        # Validate issuer
        self._validate_issuer(payload)

        # Validate audience (client ID)
        self._validate_audience(payload, client_id)

        # Verify signature with Google's public keys
        self._verify_token_signature(id_token, client_id)

        # Validate expiration
        self._validate_expiration(payload)

        # Return verified user profile information
        return self._extract_user_profile(payload)

    def _validate_token_payload(self, payload: Dict[str, Any]) -> None:
        """Validate token payload contains required fields."""
        required_fields = ["iss", "sub", "aud", "exp", "iat", "email"]
        missing_fields = [field for field in required_fields if field not in payload]

        if missing_fields:
            raise ValueError(f"Token missing required fields: {', '.join(missing_fields)}")

        # Validate field types
        if not isinstance(payload["sub"], str):
            raise ValueError("Token subject (sub) must be a string")

        if not isinstance(payload["email"], str):
            raise ValueError("Token email must be a string")

    def _validate_issuer(self, payload: Dict[str, Any]) -> None:
        """Validate token issuer is Google's accounts endpoint."""
        valid_issuers = [
            "https://accounts.google.com",
            "accounts.google.com"
        ]

        if payload["iss"] not in valid_issuers:
            raise ValueError(
                f"Invalid issuer '{payload['iss']}'. Expected one of: {', '.join(valid_issuers)}"
            )

    def _validate_audience(self, payload: Dict[str, Any], client_id: str) -> None:
        """Validate token audience matches expected client ID."""
        if payload["aud"] != client_id and payload["aud"] != "multiple":
            raise ValueError(
                f"Invalid audience '{payload['aud']}'. Expected client ID: {client_id}"
            )

    def _verify_token_signature(self, id_token: str, client_id: str) -> None:
        """
        Verify token signature using Google's public keys.

        Args:
            id_token: ID token to verify
            client_id: Client ID for audience validation

        Raises:
            ValueError: If token signature verification fails
        """
        try:
            # Get Google's public keys
            public_keys = self._get_google_public_keys()

            # Decode key ID from token header
            headers = jwt.get_unverified_header(id_token)
            key_id = headers.get("kid")

            if not key_id:
                raise ValueError("Token missing key ID (kid) in header")

            # Find matching key
            if key_id not in public_keys:
                raise ValueError(f"No matching public key found for key ID: {key_id}")

            # Verify signature
            jwt.decode(
                id_token,
                public_keys[key_id],
                algorithms=["RS256"],
                audience=client_id,
                issuer="https://accounts.google.com"
            )

        except Exception as e:
            raise ValueError(f"Token signature verification failed: {str(e)}")

    def _validate_expiration(self, payload: Dict[str, Any]) -> None:
        """Validate token expiration time."""
        current_time = datetime.now(timezone.utc).timestamp()

        if payload["exp"] <= current_time:
            raise ValueError("Token has expired")

    def _get_google_public_keys(self) -> Dict[str, Any]:
        """
        Fetch Google's public keys for token verification.

        Returns:
            Dictionary of public keys keyed by key ID

        Raises:
            ValueError: If unable to fetch public keys
        """
        try:
            with urllib.request.urlopen(self.GOOGLE_WELL_KNOWN_KEYS_URL) as response:
                keys_data = json.loads(response.read().decode("utf-8"))
                return {key["kid"]: key for key in keys_data["keys"]}
        except Exception as e:
            raise ValueError(f"Unable to fetch Google public keys: {str(e)}")

    def _extract_user_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and format user profile information from token payload.

        Args:
            payload: Verified token payload

        Returns:
            Dictionary containing user profile information
        """
        profile = {
            "sub": payload["sub"],
            "email": payload["email"],
            "email_verified": payload.get("email_verified", True),
            "name": payload.get("name"),
            "given_name": payload.get("given_name"),
            "family_name": payload.get("family_name"),
            "picture": payload.get("picture"),
            "locale": payload.get("locale"),
            "hd": payload.get("hd"),  # hosted domain for G Suite users
        }

        # Remove None values
        return {k: v for k, v in profile.items() if v is not None}