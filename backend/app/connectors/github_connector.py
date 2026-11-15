"""GitHub connector.

Wave 5A: validate a GitHub token and confirm a specific repository is
accessible with it (`connect()`).

Wave 5B (this file's other additions): discover which files in that
repository Lumora can ingest (`discover_files()`), fetch their content
(`fetch_file()`), and combine both into `sync()` - authenticate,
discover, and fetch, per `BaseConnector.sync()`'s contract ("fetch the
current state of the external source's content"). `sync()` does NOT
parse, chunk, embed, or index anything - turning fetched files into
Document/Chunk rows and Qdrant points is ConnectorService's job (see
`ConnectorService.sync_github`), via the existing DocumentService
pipeline, not this connector's. `parse()`/`index()` remain
unimplemented stubs here for that same reason.

Uses the `requests` library (already a direct project dependency -
see pyproject.toml) run inside `asyncio.to_thread` so these
authenticated GET requests don't block the event loop. No async HTTP
client (e.g. httpx) is a direct dependency of this project, and
`requests` already fully covers what's needed here, so no new
dependency is added for this connector.

The GitHub token is request-provided (see GitHubConnectorCreate /
GitHubSyncRequest / ConnectorService) and is never persisted - the
Connector model has no credential storage field, by design (see
app/models/connector.py) - and is never included in any exception
message, log line, or return value from this module.
"""

import asyncio
import base64
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from app.connectors.base import (
    BaseConnector,
    ConnectorAuthenticationError,
    ConnectorError,
    ConnectorResourceNotFoundError,
)

from app.ingestion.file_types import (
    ALLOWED_FILE_TYPES,
    CODE_FILE_TYPES,
    EXCLUDED_PATH_SEGMENTS,
    extract_extension,
    is_excluded_directory_path,
    is_minified_or_generated,
    is_secret_file,
)

GITHUB_API_BASE_URL = "https://api.github.com"
_REQUEST_TIMEOUT_SECONDS = 10

# Which paths are indexable (extension allowlist, excluded directories,
# secret/credential files, minified/generated files) is defined once in
# app.ingestion.file_types, shared with DocumentService so discovery and
# ingestion can never disagree about what is supported.
_EXCLUDED_PATH_SEGMENTS = EXCLUDED_PATH_SEGMENTS


def _is_excluded_path(path: str) -> bool:
    """True if the path must never be indexed regardless of extension."""
    return (
        is_excluded_directory_path(path)
        or is_secret_file(path)
        or is_minified_or_generated(path)
    )


def _extract_extension(path: str) -> Optional[str]:
    return extract_extension(path)


def _looks_like_text(content: bytes) -> bool:
    """False for empty, NUL-containing (binary) or non-UTF-8 content."""
    if not content.strip() or b"\x00" in content:
        return False
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return True


@dataclass
class GitHubFile:
    """Enough information about one fetched repository file for it to
    enter Lumora's existing ingestion pipeline and still be traceable
    back to its GitHub origin afterward.
    """

    repository: str
    branch: str
    path: str
    filename: str
    content: bytes
    sha: str
    url: str
    size: int


@dataclass
class GitHubFetchResult:
    """What `GitHubConnector.sync()` fetched.

    `files` contains only files that were both discovered (supported
    extension, acceptable path, under the size limit) and successfully
    fetched - a file that fails to fetch (e.g. a transient network
    error) is counted in `fetch_failures` but is not in `files`, so
    one bad file never aborts the rest of a sync.
    """

    files: List[GitHubFile]
    discovered_count: int
    fetch_failures: int


class GitHubConnector(BaseConnector):
    """Validates GitHub credentials/repository access and fetches the
    content of the repository's Lumora-ingestible files.

    `repo_full_name` is GitHub's own "owner/repo" identifier (e.g.
    "octocat/Hello-World"). `api_base_url` defaults to GitHub's public
    API and exists mainly so tests can point this at a mock server
    without patching module internals. `max_file_size_bytes`, if
    given, filters out oversized files at discovery time (before any
    content is fetched) - callers (see ConnectorService) pass the same
    limit DocumentService.upload_document already enforces, so a file
    that would be rejected there is never even fetched here.
    """

    def __init__(
        self,
        token: str,
        repo_full_name: str,
        api_base_url: str = GITHUB_API_BASE_URL,
        max_file_size_bytes: Optional[int] = None,
    ):
        self._token = token
        self._repo_full_name = repo_full_name
        self._api_base_url = api_base_url.rstrip("/")
        self._max_file_size_bytes = max_file_size_bytes
        self._default_branch: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, path: str) -> requests.Response:
        """Synchronous GET - always called via asyncio.to_thread, never directly."""
        return requests.get(
            f"{self._api_base_url}{path}",
            headers=self._headers(),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    async def connect(self) -> Dict[str, Any]:
        """Validate the token, then confirm `repo_full_name` is
        accessible with it.

        Two round trips: `GET /user` to validate the token itself
        (independent of any specific repository), then
        `GET /repos/{repo_full_name}` to confirm this token can
        access that repository specifically. The repository's default
        branch (from that second call) is cached on this instance for
        `discover_files()`/`sync()` to use.

        Raises:
            ConnectorAuthenticationError: the token is missing,
                invalid, or expired.
            ConnectorResourceNotFoundError: `repo_full_name` is
                malformed, or the repository doesn't exist / isn't
                accessible with this token.
        """
        if not self._token or not self._token.strip():
            raise ConnectorAuthenticationError("A GitHub token is required")
        if not self._repo_full_name or "/" not in self._repo_full_name:
            raise ConnectorResourceNotFoundError(
                "repo_full_name must be in 'owner/repo' form"
            )

        user_response = await asyncio.to_thread(self._get, "/user")
        if user_response.status_code == 401:
            raise ConnectorAuthenticationError("Invalid or expired GitHub token")
        if user_response.status_code != 200:
            raise ConnectorAuthenticationError(
                f"Unable to validate GitHub credentials (status {user_response.status_code})"
            )

        repo_response = await asyncio.to_thread(
            self._get, f"/repos/{self._repo_full_name}"
        )
        if repo_response.status_code == 404:
            raise ConnectorResourceNotFoundError(
                f"Repository '{self._repo_full_name}' was not found or is not accessible"
            )
        if repo_response.status_code != 200:
            raise ConnectorResourceNotFoundError(
                f"Unable to access repository '{self._repo_full_name}' "
                f"(status {repo_response.status_code})"
            )

        repo_data = repo_response.json()
        self._default_branch = repo_data.get("default_branch")

        return {
            "full_name": repo_data.get("full_name", self._repo_full_name),
            "private": repo_data.get("private"),
            "default_branch": self._default_branch,
        }

    async def discover_files(self) -> List[Dict[str, Any]]:
        """List supported, appropriately-sized files in the
        repository's default branch, already filtered.

        Filters out (without fetching any file content):
        - anything not of a Lumora-ingestible extension (shared with
          DocumentService via app.ingestion.file_types)
        - common non-source/generated directories (see
          file_types.EXCLUDED_PATH_SEGMENTS), environment/private-key/
          credential files, and minified or lock/generated files
        - files over `max_file_size_bytes`, if one was given, using
          the tree's reported blob size

        Uses one call to the Git Trees API (`recursive=1`) rather than
        walking directories one at a time.

        Must be called after `connect()` (which resolves the default
        branch) - raises ConnectorResourceNotFoundError otherwise.
        """
        if self._default_branch is None:
            raise ConnectorResourceNotFoundError(
                "connect() must succeed before discover_files() can run"
            )

        tree_response = await asyncio.to_thread(
            self._get,
            f"/repos/{self._repo_full_name}/git/trees/{self._default_branch}?recursive=1",
        )
        if tree_response.status_code != 200:
            raise ConnectorResourceNotFoundError(
                f"Unable to list files for '{self._repo_full_name}'@'{self._default_branch}' "
                f"(status {tree_response.status_code})"
            )

        tree_data = tree_response.json()
        discovered: List[Dict[str, Any]] = []

        for entry in tree_data.get("tree", []):
            if entry.get("type") != "blob":
                continue

            path = entry.get("path") or ""
            if not path or _is_excluded_path(path):
                continue

            extension = _extract_extension(path)
            if extension not in ALLOWED_FILE_TYPES:
                continue

            size = entry.get("size") or 0
            if self._max_file_size_bytes is not None and size > self._max_file_size_bytes:
                continue

            sha = entry.get("sha")
            if not sha:
                continue

            discovered.append({"path": path, "sha": sha, "size": size})

        return discovered

    async def fetch_file(self, path: str, sha: str) -> GitHubFile:
        """Fetch one file's content by blob sha (from `discover_files()`)
        and base64-decode it.

        Uses the Git Blobs API rather than the Contents API, since the
        sha is already known from the tree listing - no extra
        ref-resolution round trip is needed.

        Raises:
            ConnectorResourceNotFoundError: the blob can't be fetched
                or its content can't be decoded.
        """
        blob_response = await asyncio.to_thread(
            self._get, f"/repos/{self._repo_full_name}/git/blobs/{sha}"
        )
        if blob_response.status_code != 200:
            raise ConnectorResourceNotFoundError(
                f"Unable to fetch content for '{path}' (status {blob_response.status_code})"
            )

        blob_data = blob_response.json()
        encoding = blob_data.get("encoding")
        raw_content = blob_data.get("content", "")

        if encoding == "base64":
            try:
                content_bytes = base64.b64decode(raw_content)
            except Exception as exc:
                raise ConnectorResourceNotFoundError(
                    f"Unable to decode content for '{path}'"
                ) from exc
        else:
            content_bytes = raw_content.encode("utf-8")

        return GitHubFile(
            repository=self._repo_full_name,
            branch=self._default_branch,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            content=content_bytes,
            sha=sha,
            url=f"https://github.com/{self._repo_full_name}/blob/{self._default_branch}/{path}",
            size=len(content_bytes),
        )

    async def sync(self) -> GitHubFetchResult:
        """Authenticate, discover, and fetch content for every
        supported file in the repository.

        Does NOT parse, chunk, embed, or index anything - see this
        module's docstring. A file that fails to fetch individually is
        counted in the result's `fetch_failures` rather than aborting
        the whole sync.
        """
        await self.connect()
        discovered = await self.discover_files()

        files: List[GitHubFile] = []
        fetch_failures = 0
        for entry in discovered:
            try:
                fetched = await self.fetch_file(entry["path"], entry["sha"])
            except ConnectorError:
                fetch_failures += 1
                continue
            # The tree's reported size is advisory; enforce the limit on
            # the bytes actually received too. Source/config files must be
            # real UTF-8 text - binary or empty content is never indexed
            # (pdf/docx are binary by nature and are not text-checked).
            if (
                self._max_file_size_bytes is not None
                and len(fetched.content) > self._max_file_size_bytes
            ) or (
                _extract_extension(fetched.path) in CODE_FILE_TYPES
                and not _looks_like_text(fetched.content)
            ):
                fetch_failures += 1
                continue
            files.append(fetched)

        return GitHubFetchResult(
            files=files, discovered_count=len(discovered), fetch_failures=fetch_failures
        )

    async def parse(self, raw_content: Any) -> Any:
        raise NotImplementedError(
            "GitHub content is parsed by the existing DocumentService "
            "pipeline (see ConnectorService.sync_github), not by this method"
        )

    async def index(self, parsed_content: Any) -> Any:
        raise NotImplementedError(
            "GitHub content is indexed by the existing DocumentService "
            "pipeline (see ConnectorService.sync_github), not by this method"
        )
