"""Google Drive connector.

Wave 6A: validate a Google Drive OAuth access token and confirm the
connector's configured scope (the caller's whole Drive, or one root
folder within it) is accessible with it (`connect()`), plus discover
that scope's file/folder metadata (`discover_files()`).

This wave is foundation only - see this module's docstring on
`sync()`/`parse()`/`index()` below for what's deliberately deferred to
Wave 6B/6C: no file content is downloaded here, Google-native formats
(Docs/Sheets/Slides) are identified but not exported, and nothing is
chunked, embedded, or indexed.

Uses the `requests` library (already a direct project dependency - see
pyproject.toml) against the Drive v3 REST API directly, run inside
asyncio.to_thread so these authenticated GET requests don't block the
event loop - the same pattern GitHubConnector uses, and for the same
reason: no async HTTP client is a project dependency, and the
project's `google-auth` dependency is for verifying Google-issued ID
tokens at login (see app/auth/google_oauth_verifier.py), not for
calling Google APIs on a user's behalf - it doesn't cover this need,
so adding `google-api-python-client` (an unofficial-in-spirit,
heavyweight wrapper around the same REST calls `requests` already
makes fine) is not justified for this foundation wave.

The Drive OAuth access token is request-provided (see
GoogleDriveConnectorCreate / ConnectorService.connect_google_drive)
and is never persisted - the Connector model gains no credential
storage field for it (mirroring the GitHub connector's design; see
app/models/connector.py) - and is never included in any exception
message, log line, or return value from this module.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from app.connectors.base import (
    BaseConnector,
    ConnectorAuthenticationError,
    ConnectorError,
    ConnectorResourceNotFoundError,
)

GOOGLE_DRIVE_API_BASE_URL = "https://www.googleapis.com/drive/v3"
_REQUEST_TIMEOUT_SECONDS = 10

# Google Drive MIME type -> the file extension DocumentService already
# knows how to ingest (app.services.document_service.ALLOWED_FILE_TYPES).
# Deliberately the inverse of that set rather than a copy of it, so this
# module never drifts out of sync with what DocumentService actually
# accepts - see discover_files().
_DRIVE_MIME_TYPE_TO_EXTENSION = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
}

# Google-native formats have no downloadable byte content of their own -
# they require an explicit Drive "export" call to a target MIME type,
# which is Wave 6B's job (see this module's docstring). Discovery still
# surfaces them (flagged, not filtered out) so the caller/UI can show
# they exist, per item 9 of this wave's spec.
_GOOGLE_NATIVE_MIME_TYPES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
}

_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

_DISCOVERY_FIELDS = (
    "nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink,parents)"
)
_DISCOVERY_PAGE_SIZE = 200
# Defensive cap on pages fetched in one discover_files() call, so a
# misbehaving/huge Drive can't turn foundation-only discovery into an
# unbounded loop. Wave 6B's real ingestion sync can revisit this if a
# workspace legitimately needs more.
_MAX_DISCOVERY_PAGES = 25


@dataclass
class GoogleDriveFile:
    """Metadata for one file or folder discovered in Drive - no
    content. `extension` is Lumora's ingestible extension for this
    file's MIME type, or None if it isn't one (e.g. a folder, or a
    Google-native document awaiting Wave 6B's export handling).
    """

    file_id: str
    name: str
    mime_type: str
    is_folder: bool
    is_google_native: bool
    extension: Optional[str]
    size: Optional[int]
    modified_time: Optional[str]
    web_view_link: Optional[str]
    parents: List[str]


class GoogleDriveConnector(BaseConnector):
    """Validates a Google Drive OAuth access token and (optionally) a
    root folder scope, and discovers file/folder metadata within that
    scope.

    `root_folder_id`, if given, scopes both `connect()`'s validation
    and `discover_files()`'s listing to that single Drive folder
    (non-recursive for this wave - see `discover_files()`). If omitted,
    the connector validates and lists against the token holder's whole
    "My Drive" root instead. `api_base_url` defaults to Google's public
    Drive API and exists mainly so tests can point this at a mock
    server without patching module internals.
    """

    def __init__(
        self,
        access_token: str,
        root_folder_id: Optional[str] = None,
        api_base_url: str = GOOGLE_DRIVE_API_BASE_URL,
    ):
        self._access_token = access_token
        self._root_folder_id = root_folder_id
        self._api_base_url = api_base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Synchronous GET - always called via asyncio.to_thread, never directly."""
        return requests.get(
            f"{self._api_base_url}{path}",
            headers=self._headers(),
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    async def connect(self) -> Dict[str, Any]:
        """Validate the access token, then (if `root_folder_id` was
        given) confirm that folder is accessible with it.

        Two possible round trips: `GET /about` to validate the token
        itself and identify the connected Drive account (independent of
        any specific folder), then - only if `root_folder_id` was
        supplied - `GET /files/{root_folder_id}` to confirm this token
        can access that folder specifically and that it really is a
        folder.

        Raises:
            ConnectorAuthenticationError: the access token is missing,
                invalid, or expired.
            ConnectorResourceNotFoundError: `root_folder_id` was given
                but doesn't exist, isn't accessible with this token, or
                isn't a folder.
        """
        if not self._access_token or not self._access_token.strip():
            raise ConnectorAuthenticationError("A Google Drive access token is required")

        about_response = await asyncio.to_thread(
            self._get, "/about", {"fields": "user(emailAddress,displayName)"}
        )
        if about_response.status_code == 401:
            raise ConnectorAuthenticationError("Invalid or expired Google Drive access token")
        if about_response.status_code != 200:
            raise ConnectorAuthenticationError(
                f"Unable to validate Google Drive credentials "
                f"(status {about_response.status_code})"
            )

        about_data = about_response.json()
        user_info = about_data.get("user") or {}
        account_email = user_info.get("emailAddress")

        if self._root_folder_id:
            folder_response = await asyncio.to_thread(
                self._get,
                f"/files/{self._root_folder_id}",
                {"fields": "id,name,mimeType"},
            )
            if folder_response.status_code == 404:
                raise ConnectorResourceNotFoundError(
                    f"Drive folder '{self._root_folder_id}' was not found or is not accessible"
                )
            if folder_response.status_code != 200:
                raise ConnectorResourceNotFoundError(
                    f"Unable to access Drive folder '{self._root_folder_id}' "
                    f"(status {folder_response.status_code})"
                )

            folder_data = folder_response.json()
            if folder_data.get("mimeType") != _FOLDER_MIME_TYPE:
                raise ConnectorResourceNotFoundError(
                    f"'{self._root_folder_id}' is not a Drive folder"
                )

        return {
            "account_email": account_email,
            "root_folder_id": self._root_folder_id,
        }

    async def discover_files(self) -> List[GoogleDriveFile]:
        """List files (and folders) directly within this connector's
        scope, already annotated with Lumora-ingestibility.

        Non-recursive for this wave: only the immediate children of
        `root_folder_id` (or of "My Drive" root, if none was given) are
        listed - walking subfolders is ingestion-adjacent traversal
        that belongs with Wave 6B's actual sync, not this foundation.

        Every entry the Drive API returns is included (folders and
        Google-native documents too, each flagged via `is_folder` /
        `is_google_native`) rather than silently dropped, so a caller
        can still show what exists - filtering to only what
        DocumentService can currently ingest is the caller's decision
        (see ConnectorService), not this method's.

        Trashed items are excluded via the Drive query itself.

        Raises:
            ConnectorResourceNotFoundError: the Drive API listing call
                itself fails (e.g. the folder was accessible at
                `connect()` time but no longer is).
        """
        parent_id = self._root_folder_id or "root"
        query = f"'{parent_id}' in parents and trashed = false"

        discovered: List[GoogleDriveFile] = []
        page_token: Optional[str] = None

        for _ in range(_MAX_DISCOVERY_PAGES):
            params: Dict[str, Any] = {
                "q": query,
                "fields": _DISCOVERY_FIELDS,
                "pageSize": _DISCOVERY_PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token

            list_response = await asyncio.to_thread(self._get, "/files", params)
            if list_response.status_code != 200:
                raise ConnectorResourceNotFoundError(
                    f"Unable to list Drive files for scope '{parent_id}' "
                    f"(status {list_response.status_code})"
                )

            list_data = list_response.json()
            for entry in list_data.get("files", []):
                discovered.append(self._to_drive_file(entry))

            page_token = list_data.get("nextPageToken")
            if not page_token:
                break

        return discovered

    def _to_drive_file(self, entry: Dict[str, Any]) -> GoogleDriveFile:
        mime_type = entry.get("mimeType", "")
        size = entry.get("size")
        return GoogleDriveFile(
            file_id=entry["id"],
            name=entry.get("name", ""),
            mime_type=mime_type,
            is_folder=mime_type == _FOLDER_MIME_TYPE,
            is_google_native=mime_type in _GOOGLE_NATIVE_MIME_TYPES,
            extension=_DRIVE_MIME_TYPE_TO_EXTENSION.get(mime_type),
            size=int(size) if size is not None else None,
            modified_time=entry.get("modifiedTime"),
            web_view_link=entry.get("webViewLink"),
            parents=entry.get("parents", []),
        )

    async def sync(self) -> Any:
        raise NotImplementedError(
            "Google Drive file fetching/ingestion is Wave 6B/6C work, not "
            "implemented by this foundation-only connector yet"
        )

    async def parse(self, raw_content: Any) -> Any:
        raise NotImplementedError(
            "Google Drive content parsing (including Google-native export "
            "handling) is Wave 6B/6C work, not implemented by this "
            "foundation-only connector yet"
        )

    async def index(self, parsed_content: Any) -> Any:
        raise NotImplementedError(
            "Google Drive indexing is Wave 6B/6C work, not implemented by "
            "this foundation-only connector yet"
        )
