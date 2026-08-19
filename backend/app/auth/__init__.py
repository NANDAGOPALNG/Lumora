"""
Authentication package for Lumora.

Implements Google OAuth ID-token verification and stateless JWT
access-token issuance/validation. `oauth_handler.py` remains an unused
placeholder: Lumora verifies Google ID tokens directly and does not
perform a server-side OAuth authorization-code exchange.
"""

__all__ = [
    "auth_service",
    "oauth_handler",
    "token_manager",
    "google_oauth_verifier",
    "dependencies",
]
