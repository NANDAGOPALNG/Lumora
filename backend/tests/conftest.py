"""Test-session defaults.

Settings requires SECRET_KEY and GOOGLE_CLIENT_ID. Providing throwaway
defaults here (only when the environment doesn't already define them)
lets `pytest` run on a clean checkout without a local .env file.
Nothing here is a real credential.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")

# Shared integration-test fixtures (imported after the env defaults above,
# because importing the app reads Settings).
from tests._support import harness, storage_and_embeddings  # noqa: E402,F401
