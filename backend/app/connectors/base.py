"""Base connector abstraction.

Defines the connector lifecycle interface from the LLD's Connector
Framework (docs/Lumora_LLD.md, section 9): `connect()`, `sync()`,
`parse()`, `index()`. This module represents that lifecycle only - it
contains no source-specific behavior (GitHub, Google Drive, Notion,
etc. each live in their own module under app/connectors/ and
implement this interface).

Deliberately small: four async abstract methods and a two-exception
hierarchy, no plugin registry or generic connector-discovery
framework, per the task's instruction not to over-engineer this.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class ConnectorError(Exception):
    """Base class for all connector failures.

    Callers (ConnectorService, the connectors router) should catch
    this - or one of its subclasses below - rather than a raw
    provider-specific exception (e.g. a `requests` exception), so a
    connector implementation's own HTTP/SDK details never leak past
    it.
    """


class ConnectorAuthenticationError(ConnectorError):
    """Raised when the supplied credential is missing, invalid,
    expired, or otherwise insufficient to authenticate with the
    external source.
    """


class ConnectorResourceNotFoundError(ConnectorError):
    """Raised when the requested external resource (e.g. a specific
    GitHub repository) doesn't exist, or isn't accessible with the
    given credential.

    Deliberately the same exception whether the resource truly
    doesn't exist or the credential simply lacks access to it -
    external APIs (GitHub included) generally return 404 for both
    cases themselves, to avoid leaking which private resources exist.
    """


class BaseConnector(ABC):
    """Lifecycle interface every connector implementation follows.

    Wave 5A only exercises `connect()` (credential validation and
    resource discovery). `sync()`, `parse()`, and `index()` are part
    of Wave 5B (fetching, parsing/chunking, and Qdrant indexing) -
    they're declared here so the interface is complete per the LLD,
    but no implementation calls them yet.
    """

    @abstractmethod
    async def connect(self) -> Dict[str, Any]:
        """Validate credentials and confirm the target external
        resource is accessible.

        Returns whatever metadata about the connection the caller
        needs (e.g. to display or to derive a default connector
        name) - implementations must never include the credential
        itself in this return value, and must never log it.

        Raises:
            ConnectorAuthenticationError: the credential is missing,
                invalid, or insufficient.
            ConnectorResourceNotFoundError: the target resource
                doesn't exist or isn't accessible with this
                credential.
        """
        raise NotImplementedError

    @abstractmethod
    async def sync(self) -> Any:
        """Fetch the current state of the external source's content.

        Not implemented by any connector in Wave 5A - this is Wave 5B.
        """
        raise NotImplementedError

    @abstractmethod
    async def parse(self, raw_content: Any) -> Any:
        """Parse fetched raw content into a form ready for chunking.

        Not implemented by any connector in Wave 5A - this is Wave 5B.
        """
        raise NotImplementedError

    @abstractmethod
    async def index(self, parsed_content: Any) -> Any:
        """Chunk, embed, and index parsed content (e.g. into Qdrant).

        Not implemented by any connector in Wave 5A - this is Wave 5B.
        """
        raise NotImplementedError
