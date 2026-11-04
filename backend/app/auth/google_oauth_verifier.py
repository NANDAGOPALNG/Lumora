"""
Google OAuth ID Token verification for Lumora.

Verifies Google-issued ID tokens using the official `google-auth` library
(signature, issuer, audience, and expiration are all validated by
``google.oauth2.id_token.verify_oauth2_token``).
"""

import base64
import json
import logging
import re
import time
from typing import Any, Dict, Optional

from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config.settings import Settings

# ---------------------------------------------------------------------------
# TEMP-DIAG (remove this whole block and the calls to `_VerificationDiagnostics`
# below once the INVALID_GOOGLE_TOKEN issue is understood).
#
# Safe-by-design: never logs the Google ID token, any JWT, the email, name,
# subject or picture. Only booleans, masked public client IDs, claim *names*
# and timing offsets are written. Every line starts with "GOOGLE_AUTH_DIAG"
# and is logged at WARNING so it is visible at any configured log level.
# ---------------------------------------------------------------------------
_diag_logger = logging.getLogger("lumora.auth.diagnostics")
_JWT_RE = re.compile(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_LONG_RUN_RE = re.compile(r"[A-Za-z0-9_\-+/=]{40,}")
_CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"


def _mask_client_id(value: Any) -> str:
    """Client IDs are public, but only show enough to spot a typo."""
    if not isinstance(value, str) or not value:
        return "<missing>"
    if len(value) <= 24:
        return f"{value[:4]}...(len={len(value)})"
    return f"{value[:12]}...{value[-27:]}(len={len(value)})"


def _sanitize_message(message: str, token: str) -> str:
    """google-auth messages can embed the raw token; strip it and anything token-like."""
    if token:
        message = message.replace(token, "<token-redacted>")
    message = _JWT_RE.sub("<jwt-redacted>", message)
    message = _LONG_RUN_RE.sub("<long-value-redacted>", message)
    return message[:300]


def _unverified_claims(token: str) -> Optional[Dict[str, Any]]:
    """Decode the payload WITHOUT verifying it, for diagnostics only."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        segment = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(segment))
        return claims if isinstance(claims, dict) else None
    except Exception:  # noqa: BLE001 - diagnostics must never break auth
        return None


def _classify(exc: BaseException, message: str) -> str:
    text = message.lower()
    if isinstance(exc, google_auth_exceptions.TransportError) or "could not fetch certificates" in text:
        return "certificate_fetch (backend could not download Google's public keys)"
    if "wrong number of segments" in text or "can't parse segment" in text or "should be a json object" in text:
        return "token_parsing (value is not a well-formed JWT)"
    if "does not contain required claim" in text:
        return "token_parsing (required claim missing)"
    if "token expired" in text:
        return "expiry_validation (token expired)"
    if "used too early" in text:
        return "expiry_validation (token not yet valid: server clock behind Google's)"
    if "wrong audience" in text:
        return "audience_validation (token was issued for a different client ID)"
    if "wrong issuer" in text:
        return "issuer_validation"
    if "could not verify token signature" in text or "certificate for key id" in text:
        return "signature_verification"
    return "unknown (not recognised as a specific google-auth failure)"


class _VerificationDiagnostics:
    def __init__(self, token: str, configured_client_id: Optional[str]) -> None:
        self._token = token
        self._configured = configured_client_id
        self._claims = _unverified_claims(token)
        self._log_preflight()

    def _log(self, fmt: str, *args: Any) -> None:
        try:
            _diag_logger.warning("GOOGLE_AUTH_DIAG " + fmt, *args)
        except Exception:  # noqa: BLE001
            pass

    def _log_preflight(self) -> None:
        configured = self._configured
        well_formed = (
            isinstance(configured, str)
            and configured == configured.strip()
            and configured[:1] not in {'"', "'"}
            and configured[-1:] not in {'"', "'"}
        )
        self._log(
            "start: client_id_configured=%s configured=%s configured_has_stray_whitespace_or_quotes=%s "
            "configured_ends_with_expected_suffix=%s token_length=%d token_segments=%d",
            bool(configured),
            _mask_client_id(configured),
            (not well_formed) if configured else "n/a",
            bool(isinstance(configured, str) and configured.endswith(_CLIENT_ID_SUFFIX)),
            len(self._token or ""),
            len((self._token or "").split(".")),
        )

        claims = self._claims
        if claims is None:
            self._log("token_claims: unreadable (token is not a decodable JWT)")
            return

        now = time.time()
        aud, azp = claims.get("aud"), claims.get("azp")
        aud_matches = (aud == configured) if isinstance(aud, str) else (
            configured in aud if isinstance(aud, list) else False
        )
        exp, iat = claims.get("exp"), claims.get("iat")
        self._log(
            "token_claims: iss=%s aud_matches_configured_client_id=%s token_aud=%s token_azp=%s "
            "exp_in_seconds=%s iat_age_seconds=%s email_verified=%s has_email=%s",
            claims.get("iss"),
            aud_matches,
            _mask_client_id(aud if isinstance(aud, str) else None),
            _mask_client_id(azp if isinstance(azp, str) else None),
            round(exp - now) if isinstance(exp, (int, float)) else "n/a",
            round(now - iat) if isinstance(iat, (int, float)) else "n/a",
            claims.get("email_verified"),
            bool(claims.get("email")),
        )

    def failed(self, exc: BaseException) -> None:
        message = _sanitize_message(str(exc), self._token)
        self._log(
            "FAILED stage=%s exception_class=%s sanitized_message=%r",
            _classify(exc, str(exc)),
            f"{type(exc).__module__}.{type(exc).__name__}",
            message,
        )

    def failed_stage(self, stage: str, detail: str) -> None:
        self._log("FAILED stage=%s detail=%s", stage, detail)

    def passed(self) -> None:
        self._log(
            "signature/audience/issuer/expiry checks PASSED; any 401 after this line did not come from token verification"
        )


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
        diagnostics = _VerificationDiagnostics(id_token, client_id)  # TEMP-DIAG

        try:
            payload = google_id_token.verify_oauth2_token(
                id_token, self._request, client_id
            )
        except (ValueError, google_auth_exceptions.GoogleAuthError) as exc:
            diagnostics.failed(exc)  # TEMP-DIAG
            raise ValueError(f"Invalid Google ID token: {exc}") from exc

        diagnostics.passed()  # TEMP-DIAG

        if not payload.get("email_verified", False):
            diagnostics.failed_stage(  # TEMP-DIAG
                "email_verification", "token is valid but email_verified is not true"
            )
            raise ValueError("Google account email is not verified")

        email = payload.get("email")
        if not email:
            diagnostics.failed_stage(  # TEMP-DIAG
                "email_claims", "token is valid but contains no email claim"
            )
            raise ValueError("Google token did not include an email address")

        return self._extract_user_profile(payload)

    def _extract_user_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract only the profile fields Lumora needs from the verified token."""
        return {
            "email": payload["email"],
            "name": payload.get("name") or payload["email"],
            "picture": payload.get("picture"),
        }