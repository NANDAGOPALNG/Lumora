"""Google Drive connector.

Wave 6A: validate a Google Drive OAuth access token and confirm the
connector's configured scope (the caller's whole Drive, or one root
folder within it) is accessible with it (`connect()`), plus discover
that scope's file/folder metadata (`discover_files()`).

Wave 6B (this file's other additions): fetch one discovered file's
actual content (`fetch_file()`) - a binary download for an ordinary
supported file, or a Drive "export" to a Lumora-ingestible format for
a Google-native Doc/Sheet/Slide (see `_GOOGLE_NATIVE_EXPORT_TARGETS`).
Turning fetched content into Document/Chunk rows and Qdrant points is
still ConnectorService's job (`ConnectorService.sync_google_drive`),
via the existing DocumentService pipeline - not this connector's, so
`sync()`/`parse()`/`index()` remain unimplemented stubs below (Wave
6C's incremental sync, mirroring GitHubConnector.sync(), is expected
to be what finally implements `sync()` here).

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
makes fine) is not justified here either.

The Drive OAuth access token is request-provided (see
GoogleDriveConnectorCreate / GoogleDriveSyncRequest /
ConnectorService) and is never persisted - the Connector model gains
no credential storage field for it (mirroring the GitHub connector's
design; see app/models/connector.py) - and is never included in any
exception message, log line, chunk metadata, or return value from
this module.
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

_GOOGLE_NATIVE_MIME_TYPE_PREFIX = "application/vnd.google-apps."
_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# Google-native formats (Docs, Sheets, Slides, Drawings, Forms, ...) have
# no downloadable byte content of their own - each must be "exported" to
# an ordinary MIME type via a separate Drive API call (`fetch_file()`
# below). This maps only the native types Lumora can actually turn into
# something DocumentService already knows how to ingest, to the export
# MIME type/extension pair to request - chosen as the closest existing
# ALLOWED_FILE_TYPES match Drive itself offers for each (Docs export
# losslessly to .docx; Sheets and Slides have no supported tabular/deck
# format in ALLOWED_FILE_TYPES, so both fall back to a PDF export - a
# faithful enough rendering for retrieval, not a data/formatting
# preservation guarantee). `discover_files()` still flags any
# "application/vnd.google-apps.*" type (via `is_google_native`) even if
# it isn't a key here (e.g. a Drawing or a Form) - `fetch_file()` raises
# a clear, non-credential-leaking error for those rather than guessing a
# parser for them, per this wave's spec (do not invent new parsers).
_GOOGLE_NATIVE_EXPORT_TARGETS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "application/vnd.google-apps.spreadsheet": ("application/pdf", "pdf"),
    "application/vnd.google-apps.presentation": ("application/pdf", "pdf"),
}

_DISCOVERY_FIELDS = (
    "nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink,parents)"
)
_DISCOVERY_PAGE_SIZE = 200
# Defensive cap on pages fetched in one discover_files() call, so a
# misbehaving/huge Drive can't turn foundation-only discovery into an
# unbounded loop. Wave 6C's incremental sync can revisit this if a
# workspace legitimately needs more.
_MAX_DISCOVERY_PAGES = 25


@dataclass
class GoogleDriveFile:
    """Metadata for one file or folder discovered in Drive - no
    content. `extension` is Lumora's ingestible extension for this
    file's MIME type, or None if it isn't one (e.g. a folder, or a
    Google-native document - `fetch_file()` resolves the latter's
    actual export extension separately, since it isn't determined by
    `mime_type` alone).
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


@dataclass
class GoogleDriveFetchedFile:
    """One discovered file's actual, Lumora-ingestible content -
    downloaded as-is for an ordinary supported file, or exported for a
    Google-native Doc/Sheet/Slide (see `_GOOGLE_NATIVE_EXPORT_TARGETS`).

    `filename` always ends in `.{file_type}` (Drive doesn't guarantee a
    native document's display `name` has any extension at all, let
    alone the export's), so DocumentService's own extension-based
    validation (`_extract_file_type`) accepts it unmodified.
    `mime_type` is the *content's* actual MIME type (the export target,
    for a Google-native file - not the original `application/vnd.google-apps.*`
    type, which describes no downloadable bytes).
    """

    file_id: str
    filename: str
    content: bytes
    file_type: str
    mime_type: str
    size: int
    modified_time: Optional[str]
    web_view_link: Optional[str]


def _ensure_extension(name: str, extension: str) -> str:
    suffix = f".{extension}"
    if name.lower().endswith(suffix):
        return name
    return f"{name}{suffix}"


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
        is_folder = mime_type == _FOLDER_MIME_TYPE
        return GoogleDriveFile(
            file_id=entry["id"],
            name=entry.get("name", ""),
            mime_type=mime_type,
            is_folder=is_folder,
            is_google_native=(
                not is_folder and mime_type.startswith(_GOOGLE_NATIVE_MIME_TYPE_PREFIX)
            ),
            extension=_DRIVE_MIME_TYPE_TO_EXTENSION.get(mime_type),
            size=int(size) if size is not None else None,
            modified_time=entry.get("modifiedTime"),
            web_view_link=entry.get("webViewLink"),
            parents=entry.get("parents", []),
        )

    async def fetch_file(self, file: GoogleDriveFile) -> GoogleDriveFetchedFile:
        """Fetch one discovered file's actual content: a binary
        download for an ordinary supported file, or a Drive export for
        a supported Google-native Doc/Sheet/Slide.

        `file` should be an entry `discover_files()` returned for this
        same connector scope - its `file_id`/`is_google_native`/
        `mime_type`/`extension` are what decide which Drive API call is
        made and what the resulting `file_type` is.

        Raises:
            ValueError: `file` isn't something this method can fetch at
                all - a folder, or a non-native file whose MIME type
                isn't one of Lumora's ingestible extensions
                (`extension` is None and it isn't Google-native). This
                is a caller/filtering bug, not an external failure, so
                it isn't a ConnectorError - callers (see
                ConnectorService.sync_google_drive) are expected to
                have already filtered `discover_files()`'s results
                before calling this.
            ConnectorResourceNotFoundError: the file is a Google-native
                type this connector has no supported export mapping
                for (e.g. a Drawing or a Form - see
                `_GOOGLE_NATIVE_EXPORT_TARGETS`), or the download/export
                call itself fails (moved, deleted, or no longer
                accessible with this token since it was discovered).
        """
        if file.is_folder:
            raise ValueError(f"'{file.name}' is a folder, not a file")

        if file.is_google_native:
            export_target = _GOOGLE_NATIVE_EXPORT_TARGETS.get(file.mime_type)
            if export_target is None:
                raise ConnectorResourceNotFoundError(
                    f"'{file.name}' ({file.mime_type}) is a Google-native format "
                    f"with no supported export mapping to an ingestible type"
                )
            export_mime_type, extension = export_target
            response = await asyncio.to_thread(
                self._get,
                f"/files/{file.file_id}/export",
                {"mimeType": export_mime_type},
            )
            final_mime_type = export_mime_type
        else:
            if file.extension is None:
                raise ValueError(
                    f"'{file.name}' ({file.mime_type}) is not a Lumora-ingestible type"
                )
            extension = file.extension
            response = await asyncio.to_thread(
                self._get, f"/files/{file.file_id}", {"alt": "media"}
            )
            final_mime_type = file.mime_type

        if response.status_code != 200:
            raise ConnectorResourceNotFoundError(
                f"Unable to fetch content for '{file.name}' (status {response.status_code})"
            )

        content = response.content

        return GoogleDriveFetchedFile(
            file_id=file.file_id,
            filename=_ensure_extension(file.name, extension),
            content=content,
            file_type=extension,
            mime_type=final_mime_type,
            size=len(content),
            modified_time=file.modified_time,
            web_view_link=file.web_view_link,
        )

    async def sync(self) -> Any:
        raise NotImplementedError(
            "Google Drive incremental sync (change/delete reconciliation) "
            "is Wave 6C work, not implemented by this connector yet - see "
            "ConnectorService.sync_google_drive for Wave 6B's full-ingestion "
            "orchestration, which calls discover_files()/fetch_file() "
            "directly instead"
        )

    async def parse(self, raw_content: Any) -> Any:
        raise NotImplementedError(
            "Google Drive content is parsed by the existing DocumentService "
            "pipeline (see ConnectorService.sync_google_drive), not by this method"
        )

    async def index(self, parsed_content: Any) -> Any:
        raise NotImplementedError(
            "Google Drive content is indexed by the existing DocumentService "
            "pipeline (see ConnectorService.sync_google_drive), not by this method"
        )
