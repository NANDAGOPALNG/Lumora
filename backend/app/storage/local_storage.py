"""
Local filesystem storage for uploaded documents.

This is a development-only storage implementation: it writes files
under a single configured root directory, keyed by document UUID
rather than the client-supplied filename. There is no provider
abstraction here (no S3/R2/GCS/Azure) - the project's design
documents don't specify a cloud object-storage provider, so this
module only supports what document upload/delete currently need.
"""

import os
from pathlib import Path
from uuid import UUID

from app.config.settings import Settings


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
