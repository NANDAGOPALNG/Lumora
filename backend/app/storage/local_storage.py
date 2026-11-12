"""
Local filesystem storage for uploaded documents.

Writes files under a single configured root directory, keyed by document
UUID rather than the client-supplied filename. This is the storage used for
development and tests (DOCUMENT_STORAGE_BACKEND=local, the default) and for
every document stored before Cloudflare R2 support existed - those
documents' `storage_path` values are absolute filesystem paths and keep
being read, rewritten and deleted here.

The module-level functions below are the original, synchronous interface
and are unchanged. `LocalStorage` adapts them to the async `StorageBackend`
interface (app.storage.base) used by the services.
"""

import asyncio
import os
from pathlib import Path
from uuid import UUID

from app.config.settings import Settings
from app.storage.base import StorageBackend, StorageError, StorageNotFoundError


def _storage_root() -> Path:
    settings = Settings.get_instance()
    root = Path(settings.document_storage_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def generate_storage_path(document_id: UUID, file_type: str) -> str:
    """Generate a collision-safe storage path for a document.

    The stored filename is derived only from the document's own UUID and
    a sanitized extension - never from the client-supplied filename - so
    there is no path-traversal input to sanitize in the first place.
    """
    root = _storage_root()
    safe_extension = "".join(ch for ch in file_type.lower() if ch.isalnum())
    filename = f"{document_id}.{safe_extension}" if safe_extension else str(document_id)
    return str(root / filename)


def save_file(storage_path: str, content: bytes) -> None:
    """Write file content to storage_path.

    Refuses to write outside the configured storage root, as a defensive
    check even though `generate_storage_path` never produces a path that
    could escape it.
    """
    root = _storage_root()
    target = Path(storage_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Refusing to write outside the configured storage directory")

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        f.write(content)


def delete_file(storage_path: str) -> None:
    """Delete a stored file. A file that's already missing is not an error."""
    try:
        os.remove(storage_path)
    except FileNotFoundError:
        pass


def read_file(storage_path: str) -> bytes:
    """Read a stored file. Raises FileNotFoundError if it is missing.

    Like `delete_file`, this deliberately does not restrict the path to the
    current storage root: documents stored before this module was
    abstracted keep the absolute path they were saved under, and that must
    stay readable even if DOCUMENT_STORAGE_PATH was later changed. The path
    comes from the database, never from a client request.
    """
    with open(storage_path, "rb") as f:
        return f.read()


class LocalStorage(StorageBackend):
    """The local filesystem as a `StorageBackend` (blocking I/O runs in a
    worker thread so the event loop is never blocked)."""

    name = "local"

    def generate_storage_path(self, document_id: UUID, file_type: str) -> str:
        return generate_storage_path(document_id, file_type)

    async def save(self, storage_path: str, content: bytes) -> None:
        try:
            await asyncio.to_thread(save_file, storage_path, content)
        except ValueError as exc:  # path outside the storage root
            raise StorageError(str(exc)) from exc
        except OSError as exc:
            raise StorageError(f"Local storage write failed: {type(exc).__name__}") from exc

    async def read(self, storage_path: str) -> bytes:
        try:
            return await asyncio.to_thread(read_file, storage_path)
        except FileNotFoundError as exc:
            raise StorageNotFoundError("Stored file not found") from exc
        except OSError as exc:
            raise StorageError(f"Local storage read failed: {type(exc).__name__}") from exc

    async def delete(self, storage_path: str) -> None:
        try:
            await asyncio.to_thread(delete_file, storage_path)
        except OSError as exc:
            raise StorageError(f"Local storage delete failed: {type(exc).__name__}") from exc

    async def exists(self, storage_path: str) -> bool:
        return await asyncio.to_thread(os.path.isfile, storage_path)
