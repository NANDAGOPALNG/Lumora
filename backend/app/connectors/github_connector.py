"""GitHub connector (Wave 5A).

Wave 5A responsibilities only: validate a GitHub token and confirm
that a specific repository is accessible with it. No file
fetching/parsing/chunking/embedding/Qdrant indexing happens here -
those are Wave 5B; `sync()`, `parse()`, and `index()` are required
overrides of `BaseConnector` but are not implemented, and raise
`NotImplementedError` if ever called.

Uses the `requests` library (already a direct project dependency -
see pyproject.toml) run inside `asyncio.to_thread` so the couple of
simple authenticated GET requests this needs don't block the event
loop. No async HTTP client (e.g. httpx) is a direct dependency of this
project, and `requests` already fully covers what's needed here, so
no new dependency is added for this connector.

The GitHub token is request-provided (see GitHubConnectorCreate /
ConnectorService) and is never persisted - the Connector model has no
credential storage field, by design (see app/models/connector.py) -
and is never included in any exception message, log line, or return
value from this module.
"""

import asyncio
from typing import Any, Dict

import requests

from app.connectors.base import (
    BaseConnector,
    ConnectorAuthenticationError,
    ConnectorResourceNotFoundError,
)

GITHUB_API_BASE_URL = "https://api.github.com"
_REQUEST_TIMEOUT_SECONDS = 10


class GitHubConnector(BaseConnector):
    """Validates a GitHub token and a repository's accessibility.

    `repo_full_name` is GitHub's own "owner/repo" identifier (e.g.
    "octocat/Hello-World"). `api_base_url` defaults to GitHub's public
    API and exists mainly so tests can point this at a mock server
    without patching module internals.
    """

    def __init__(
        self,
        token: str,
        repo_full_name: str,
        api_base_url: str = GITHUB_API_BASE_URL,
    ):
        self._token = token
        self._repo_full_name = repo_full_name
        self._api_base_url = api_base_url.rstrip("/")

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
        access that repository specifically.

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
        return {
            "full_name": repo_data.get("full_name", self._repo_full_name),
            "private": repo_data.get("private"),
            "default_branch": repo_data.get("default_branch"),
        }

    async def sync(self) -> Any:
        raise NotImplementedError("GitHub sync is implemented in Wave 5B")

    async def parse(self, raw_content: Any) -> Any:
        raise NotImplementedError("GitHub parse is implemented in Wave 5B")

    async def index(self, parsed_content: Any) -> Any:
        raise NotImplementedError("GitHub index is implemented in Wave 5B")
