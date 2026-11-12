"""Choose the storage provider.

- New uploads go to the provider named by DOCUMENT_STORAGE_BACKEND
  ("local", the default, or "r2").
- An *existing* document is always handled by the provider that owns its
  `storage_path`, whatever DOCUMENT_STORAGE_BACKEND is now:
    * "r2://<key>"   -> Cloudflare R2
    * anything else  -> local filesystem (every path written before R2
      support is an absolute filesystem path, which can never start with
      "r2://"; see app.storage.base).
  This is what keeps legacy local documents readable after R2 is enabled,
  with no database migration.
"""

import logging
from typing import Optional, Tuple

from app.config.settings import Settings
from app.storage.base import (
    StorageBackend,
    StorageConfigurationError,
    StorageError,
)
from app.storage.local_storage import LocalStorage
from app.storage.r2_storage import R2_SCHEME, R2Storage, resolve_r2_config

logger = logging.getLogger(__name__)

BACKEND_LOCAL = "local"
BACKEND_R2 = "r2"

_local = LocalStorage()
# (config fingerprint, provider): the boto3 client is built once and reused.
_r2_cache: Optional[Tuple[tuple, R2Storage]] = None


def reset_cache() -> None:
    """Drop the cached R2 provider (used by tests)."""
    global _r2_cache
    _r2_cache = None


def configured_backend(settings: Optional[Settings] = None) -> str:
    settings = settings or Settings.get_instance()
    backend = (settings.document_storage_backend or BACKEND_LOCAL).strip().lower()
    if backend not in (BACKEND_LOCAL, BACKEND_R2):
        raise StorageConfigurationError(
            f"DOCUMENT_STORAGE_BACKEND must be '{BACKEND_LOCAL}' or '{BACKEND_R2}'"
        )
    return backend


def _get_r2(settings: Settings) -> R2Storage:
    global _r2_cache
    config = resolve_r2_config(settings)  # validates; raises with names only
    fingerprint = (
        config["endpoint_url"],
        config["bucket"],
        config["access_key_id"],
        config["secret_access_key"],
    )
    if _r2_cache is None or _r2_cache[0] != fingerprint:
        _r2_cache = (fingerprint, R2Storage.from_settings(settings))
    return _r2_cache[1]


def get_storage_for_new_documents() -> StorageBackend:
    """The provider that new uploads are written to."""
    settings = Settings.get_instance()
    if configured_backend(settings) == BACKEND_R2:
        return _get_r2(settings)
    return _local


def get_storage_for_path(storage_path: str) -> StorageBackend:
    """The provider that owns an existing document's `storage_path`."""
    if isinstance(storage_path, str) and storage_path.startswith(R2_SCHEME):
        return _get_r2(Settings.get_instance())
    return _local


def validate_storage_configuration() -> None:
    """Fail fast at startup if the selected provider is misconfigured.

    Raises StorageConfigurationError naming the missing variables (never
    their values). Makes no network call.
    """
    settings = Settings.get_instance()
    if configured_backend(settings) == BACKEND_R2:
        resolve_r2_config(settings)


async def delete_stored_file(storage_path: str) -> bool:
    """Best-effort deletion used after a document's database row is gone.

    A missing object counts as success. A storage failure is logged (without
    secrets) and returns False instead of raising, because the database row
    is already deleted and failing the caller's delete would help nobody -
    the same policy already applied to Qdrant cleanup. Returns True if the
    object is gone.
    """
    try:
        await get_storage_for_path(storage_path).delete(storage_path)
        return True
    except StorageError as exc:  # includes StorageConfigurationError
        logger.error("Could not delete stored document file (%s): %s", storage_path, exc)
        return False
