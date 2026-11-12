"""Common interface and errors for document storage providers.

A document's `storage_path` column is an opaque *reference* owned by the
provider that wrote it. Services never interpret it - they hand it back to
the provider (see `app.storage.factory.get_storage_for_path`).

Reference formats:
- local: an absolute filesystem path (the format used before R2 support).
- r2:    "r2://<object key>", e.g. "r2://documents/<document uuid>.pdf".
"""

from abc import ABC, abstractmethod
from uuid import UUID


class StorageError(Exception):
    """A storage operation failed. Messages never contain credentials."""


class StorageNotFoundError(StorageError):
    """The stored object does not exist."""


class StorageConfigurationError(StorageError):
    """The selected storage provider is missing or has invalid configuration.

    Messages name the offending environment variables but never their values.
    """


def sanitize_extension(file_type: str) -> str:
    """Keep only lowercase alphanumerics, so a file type can never inject a
    path separator or traversal sequence into a storage reference."""
    return "".join(ch for ch in file_type.lower() if ch.isalnum())


class StorageBackend(ABC):
    """A place document bytes can be saved to, read from and deleted from.

    Every method that takes `storage_path` expects a reference this same
    provider produced via `generate_storage_path`.
    """

    #: Short provider name, e.g. "local" or "r2".
    name: str

    @abstractmethod
    def generate_storage_path(self, document_id: UUID, file_type: str) -> str:
        """Return a new reference for a document. Derived only from the
        document's UUID and a sanitized extension - never from the
        client-supplied filename."""

    @abstractmethod
    async def save(self, storage_path: str, content: bytes) -> None:
        """Write `content`, replacing any existing object at `storage_path`."""

    @abstractmethod
    async def read(self, storage_path: str) -> bytes:
        """Return the stored bytes.

        Raises:
            StorageNotFoundError: nothing is stored at `storage_path`.
            StorageError: the read failed for any other reason.
        """

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Delete the stored object. A missing object is not an error."""

    @abstractmethod
    async def exists(self, storage_path: str) -> bool:
        """Whether an object is stored at `storage_path`."""
