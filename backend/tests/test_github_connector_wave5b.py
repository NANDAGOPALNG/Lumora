"""Focused tests for GitHubConnector's Wave 5B additions: discovery,
filtering, content fetch, and the two failure modes carried over from
Wave 5A (auth / repo access).

All GitHub API calls are mocked via monkeypatching
`requests.get` as seen by `app.connectors.github_connector` - no real
token or network access is used or required.
"""

import asyncio
import base64

import pytest

from app.connectors import github_connector as github_connector_module
from app.connectors.base import ConnectorAuthenticationError, ConnectorResourceNotFoundError
from app.connectors.github_connector import GitHubConnector


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# A repo tree mixing supported files, unsupported extensions, an
# oversized file, and junk/generated directories - every filtering
# rule discover_files() applies gets exercised by this one fixture.
_SAMPLE_TREE = {
    "tree": [
        {"path": "README.md", "type": "blob", "sha": "sha-readme", "size": 120},
        {"path": "docs/guide.txt", "type": "blob", "sha": "sha-guide", "size": 300},
        {"path": "src/app.py", "type": "blob", "sha": "sha-py", "size": 500},  # unsupported ext
        {"path": "assets/logo.png", "type": "blob", "sha": "sha-png", "size": 900},  # unsupported ext
        {"path": "huge.md", "type": "blob", "sha": "sha-huge", "size": 10_000_000},  # too big
        {"path": "node_modules/pkg/readme.md", "type": "blob", "sha": "sha-nm", "size": 50},  # excluded dir
        {"path": ".git/HEAD", "type": "blob", "sha": "sha-git", "size": 10},  # excluded dir + unsupported ext
        {"path": "docs", "type": "tree", "sha": "sha-tree-dir", "size": 0},  # a directory, not a blob
    ]
}


def _mock_github(monkeypatch, *, user_status=200, repo_status=200, tree_status=200,
                  tree_json=None, blob_status=200, blob_json_by_sha=None):
    repo_json = {"full_name": "octocat/Hello-World", "private": False, "default_branch": "main"}
    tree_json = tree_json if tree_json is not None else _SAMPLE_TREE
    blob_json_by_sha = blob_json_by_sha or {}

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/user"):
            return _FakeResponse(user_status, {})
        if "/git/trees/" in url:
            return _FakeResponse(tree_status, tree_json)
        if "/git/blobs/" in url:
            sha = url.rsplit("/", 1)[-1]
            return _FakeResponse(blob_status, blob_json_by_sha.get(sha, {}))
        return _FakeResponse(repo_status, repo_json)

    monkeypatch.setattr(github_connector_module.requests, "get", fake_get)


def test_repository_file_discovery_and_filtering(monkeypatch):
    _mock_github(monkeypatch)

    async def _run():
        connector = GitHubConnector(
            token="tok", repo_full_name="octocat/Hello-World", max_file_size_bytes=1_000_000
        )
        await connector.connect()
        discovered = await connector.discover_files()
        return {entry["path"] for entry in discovered}

    paths = asyncio.run(_run())

    # supported, correctly-sized, not in an excluded directory
    assert paths == {"README.md", "docs/guide.txt"}
    # explicitly confirm each filtering rule excluded what it should
    assert "src/app.py" not in paths           # unsupported extension
    assert "assets/logo.png" not in paths       # unsupported extension
    assert "huge.md" not in paths               # over max_file_size_bytes
    assert "node_modules/pkg/readme.md" not in paths  # excluded directory
    assert ".git/HEAD" not in paths             # excluded directory


def test_github_file_content_retrieval(monkeypatch):
    _mock_github(
        monkeypatch,
        blob_json_by_sha={
            "sha-readme": {"content": _b64("# Hello\n\nThis is the readme."), "encoding": "base64"},
        },
    )

    async def _run():
        connector = GitHubConnector(token="tok", repo_full_name="octocat/Hello-World")
        await connector.connect()
        return await connector.fetch_file("README.md", "sha-readme")

    fetched = asyncio.run(_run())

    assert fetched.content == b"# Hello\n\nThis is the readme."
    assert fetched.path == "README.md"
    assert fetched.filename == "README.md"
    assert fetched.repository == "octocat/Hello-World"
    assert fetched.branch == "main"
    assert fetched.sha == "sha-readme"
    assert fetched.url == "https://github.com/octocat/Hello-World/blob/main/README.md"


def test_sync_discovers_and_fetches_only_supported_files(monkeypatch):
    _mock_github(
        monkeypatch,
        blob_json_by_sha={
            "sha-readme": {"content": _b64("readme text"), "encoding": "base64"},
            "sha-guide": {"content": _b64("guide text"), "encoding": "base64"},
        },
    )

    async def _run():
        connector = GitHubConnector(
            token="tok", repo_full_name="octocat/Hello-World", max_file_size_bytes=1_000_000
        )
        return await connector.sync()

    result = asyncio.run(_run())

    assert result.discovered_count == 2
    assert result.fetch_failures == 0
    assert {f.path for f in result.files} == {"README.md", "docs/guide.txt"}
    assert {f.content for f in result.files} == {b"readme text", b"guide text"}


def test_authentication_failure(monkeypatch):
    _mock_github(monkeypatch, user_status=401)

    async def _run():
        connector = GitHubConnector(token="bad-token", repo_full_name="octocat/Hello-World")
        await connector.connect()

    with pytest.raises(ConnectorAuthenticationError):
        asyncio.run(_run())


def test_repository_access_failure(monkeypatch):
    _mock_github(monkeypatch, user_status=200, repo_status=404)

    async def _run():
        connector = GitHubConnector(token="tok", repo_full_name="octocat/does-not-exist")
        await connector.connect()

    with pytest.raises(ConnectorResourceNotFoundError):
        asyncio.run(_run())


def test_sync_skips_individual_fetch_failures_without_aborting(monkeypatch):
    # README fetches fine; guide.txt's blob call 500s.
    _mock_github(
        monkeypatch,
        blob_status=200,
        blob_json_by_sha={"sha-readme": {"content": _b64("ok"), "encoding": "base64"}},
    )

    call_count = {"n": 0}
    real_get = github_connector_module.requests.get

    def flaky_get(url, headers=None, timeout=None):
        if "/git/blobs/sha-guide" in url:
            return _FakeResponse(500, {})
        return real_get(url, headers=headers, timeout=timeout)

    async def _run():
        connector = GitHubConnector(
            token="tok", repo_full_name="octocat/Hello-World", max_file_size_bytes=1_000_000
        )
        return await connector.sync()

    github_connector_module.requests.get = flaky_get
    try:
        result = asyncio.run(_run())
    finally:
        github_connector_module.requests.get = real_get

    assert result.discovered_count == 2
    assert result.fetch_failures == 1
    assert [f.path for f in result.files] == ["README.md"]
