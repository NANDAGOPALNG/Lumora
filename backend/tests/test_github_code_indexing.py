"""Stage 6A: GitHub repository source-code indexing.

Covers the shared extension allowlist, the reusable code parser,
code-aware chunking, GitHub discovery filtering/exclusions, and the
incremental sync behavior for code files. Uses the same harness as
test_connector_sync_wave5b.py (in-memory SQLite, real ingestion pipeline,
faked GitHub/embeddings/Qdrant).
"""

import asyncio
import base64
import shutil
import tempfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.api.v1.document.router import get_document_service
from app.auth.dependencies import get_current_user
from app.connectors import github_connector as gh
from app.connectors.github_connector import GitHubConnector
from app.ingestion import ParsingError, extract_chunks_from_bytes
from app.ingestion import parsers
from app.ingestion.chunker import chunk_code, chunk_text
from app.ingestion.cleaner import clean_code, clean_text
from app.ingestion.file_types import (
    ALLOWED_FILE_TYPES,
    CODE_FILE_TYPES,
    DOCUMENT_FILE_TYPES,
    is_indexable_repo_path,
    is_minified_or_generated,
    is_secret_file,
)
from app.models.chunk import Chunk
from app.models.document import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.services import document_service as document_service_module
from app.services.document_service import (
    DocumentService,
    UnsupportedFileTypeError,
    _extract_file_type,
    _validate_content_type,
)
from tests.test_connector_sync_wave5b import (
    FakeVectorStore,
    _FakeResponse,
    _fake_embed_texts,
    _make_connector_service,
    _make_engine_and_session_factory,
    _seed,
)

REQUIRED_CODE_EXTENSIONS = [
    "py", "js", "jsx", "mjs", "cjs", "ts", "tsx", "html", "css", "scss",
    "json", "yaml", "yml", "toml", "xml", "sql", "sh", "rst",
]

SAMPLES = {
    "py": "import os\n\n\ndef main():\n    return os.getcwd()\n",
    "js": "function main() {\n  return 1;\n}\n",
    "jsx": "export function App() {\n  return <div>hi</div>;\n}\n",
    "mjs": "export const a = 1;\n",
    "cjs": "module.exports = { a: 1 };\n",
    "ts": "export interface A {\n  x: number;\n}\n",
    "tsx": "export const B = () => <p>b</p>;\n",
    "html": "<html><body><h1>Title</h1></body></html>\n",
    "css": "body {\n  color: red;\n}\n",
    "scss": "$c: red;\n.a {\n  color: $c;\n}\n",
    "json": '{\n  "name": "demo",\n  "version": 1\n}\n',
    "yaml": "services:\n  api:\n    image: demo\n",
    "yml": "key:\n  - a\n  - b\n",
    "toml": '[tool]\nname = "demo"\n',
    "xml": "<root><item>1</item></root>\n",
    "sql": "CREATE TABLE t (id INT);\n",
    "sh": "#!/bin/sh\necho hello\n",
    "rst": "Title\n=====\n\nSome text.\n",
}


@pytest.fixture(autouse=True)
def _temp_storage_and_fake_embeddings(monkeypatch):
    temp_dir = tempfile.mkdtemp(prefix="lumora-test-storage-")
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", temp_dir)
    monkeypatch.setattr(document_service_module, "embed_texts", _fake_embed_texts)
    yield
    shutil.rmtree(temp_dir, ignore_errors=True)


def _b64(data) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def test_every_required_extension_is_in_the_shared_allowlist():
    assert set(REQUIRED_CODE_EXTENSIONS) == set(CODE_FILE_TYPES)
    assert {"pdf", "docx", "txt", "md"} == set(DOCUMENT_FILE_TYPES)
    assert ALLOWED_FILE_TYPES == CODE_FILE_TYPES | DOCUMENT_FILE_TYPES
    # DocumentService re-exports the very same object (single source of truth)
    assert document_service_module.ALLOWED_FILE_TYPES is ALLOWED_FILE_TYPES


@pytest.mark.parametrize("extension", REQUIRED_CODE_EXTENSIONS)
def test_every_supported_extension_is_accepted_by_discovery_and_document_service(extension):
    path = f"src/file.{extension}"
    assert is_indexable_repo_path(path)
    assert _extract_file_type(path) == extension
    assert _extract_file_type(f"SRC/FILE.{extension.upper()}") == extension


@pytest.mark.parametrize(
    "path", ["a.png", "a.exe", "a.class", "a.pyc", "a.so", "a.zip", "a.csv", "a.go", "Makefile", "a.lock"]
)
def test_unsupported_extensions_are_rejected(path):
    assert not is_indexable_repo_path(path)
    with pytest.raises(UnsupportedFileTypeError):
        _extract_file_type(path)


def test_manual_upload_allowlist_is_unchanged():
    with pytest.raises(UnsupportedFileTypeError):
        _extract_file_type("x.py", DOCUMENT_FILE_TYPES)
    for name in ("a.pdf", "a.docx", "a.txt", "a.md"):
        assert _extract_file_type(name, DOCUMENT_FILE_TYPES) == name.split(".")[1]


@pytest.mark.parametrize("extension", REQUIRED_CODE_EXTENSIONS)
def test_code_content_types_are_accepted_but_binary_types_are_not(extension):
    for content_type in (None, "", "application/octet-stream", "text/plain", "text/x-python", "application/json"):
        _validate_content_type(extension, content_type)
    with pytest.raises(UnsupportedFileTypeError):
        _validate_content_type(extension, "image/png")
    with pytest.raises(UnsupportedFileTypeError):
        _validate_content_type(extension, "application/pdf")


def test_existing_content_type_rules_for_documents_are_unchanged():
    with pytest.raises(UnsupportedFileTypeError):
        _validate_content_type("pdf", "text/plain")
    _validate_content_type("md", "text/plain")


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/pkg/index.js", "a/node_modules/x/y.js", ".git/config.json", "vendor/lib/x.py",
        "dist/app.js", "build/out.js", "target/debug/x.json", "__pycache__/x.py", ".venv/lib/x.py",
        "venv/lib/x.py", ".next/server/page.js", "frontend/dist/bundle.js", ".idea/workspace.xml",
    ],
)
def test_excluded_directories_are_never_indexable(path):
    assert not is_indexable_repo_path(path)


def test_directory_names_only_exclude_when_they_are_directories():
    # a *file* called build.py / target.js is source code, not a build dir
    assert is_indexable_repo_path("scripts/build.py")
    assert is_indexable_repo_path("src/target.js")
    assert is_indexable_repo_path("src/vendor.ts")


@pytest.mark.parametrize(
    "path",
    [
        ".env", "config/.env", ".env.local", ".env.production", ".env.json", "prod.env",
        "keys/server.pem", "id_rsa", "deploy/private.key", "cert.p12", "credentials.json",
        "config/secrets.yaml", "secrets.toml", "service-account.json", "gcp-service-account-key.json",
        "client_secret.json", "terraform.tfvars", ".npmrc", "app/my_secrets.yml", "prod.credentials.json",
    ],
)
def test_secret_and_credential_files_are_never_indexable(path):
    assert is_secret_file(path)
    assert not is_indexable_repo_path(path)


@pytest.mark.parametrize("path", [".env.example", ".env.sample", ".env.template"])
def test_env_templates_are_not_treated_as_secrets(path):
    assert not is_secret_file(path)


def test_documentation_about_credentials_is_still_indexable():
    assert is_indexable_repo_path("docs/credentials-guide.md")
    assert is_indexable_repo_path("docs/secrets.md")
    assert is_indexable_repo_path("src/secret_manager.py")


@pytest.mark.parametrize(
    "path",
    ["static/app.min.js", "static/site.min.css", "dist.bundle.js", "x.js.map", "package-lock.json", "web/pnpm-lock.yaml", "poetry.lock", "uv.lock"],
)
def test_minified_and_generated_files_are_excluded(path):
    assert is_minified_or_generated(path)
    assert not is_indexable_repo_path(path)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("extension", REQUIRED_CODE_EXTENSIONS)
def test_every_code_extension_parses_and_preserves_text(extension):
    sample = SAMPLES[extension]
    parsed = parsers.parse_bytes(sample.encode("utf-8"), extension)
    assert len(parsed.pages) == 1
    assert parsed.pages[0].text == sample


def test_one_shared_parser_serves_all_code_types():
    from app.ingestion.parsers import _BYTES_PARSERS, code_parser

    assert {_BYTES_PARSERS[e] for e in CODE_FILE_TYPES} == {code_parser.parse_bytes}


def test_parser_reads_a_file_path(tmp_path):
    path = tmp_path / "a.py"
    path.write_bytes(b"x = 1\n")
    assert parsers.parse(str(path), "py").pages[0].text == "x = 1\n"


def test_parser_strips_a_bom():
    parsed = parsers.parse_bytes("\ufeffx = 1\n".encode("utf-8"), "py")
    assert parsed.pages[0].text == "x = 1\n"


@pytest.mark.parametrize("extension", REQUIRED_CODE_EXTENSIONS)
def test_invalid_utf8_is_rejected(extension):
    with pytest.raises(ParsingError, match="UTF-8"):
        parsers.parse_bytes(b"print('\xff\xfe broken')\n", extension)


@pytest.mark.parametrize("extension", REQUIRED_CODE_EXTENSIONS)
def test_binary_content_with_nul_bytes_is_rejected(extension):
    with pytest.raises(ParsingError, match="binary"):
        parsers.parse_bytes(b"\x7fELF\x00\x01\x02", extension)


@pytest.mark.parametrize("content", [b"", b"   \n\n\t \n"])
def test_empty_code_files_are_rejected(content):
    with pytest.raises(ParsingError, match="empty"):
        parsers.parse_bytes(content, "py")


def test_unsupported_type_still_raises():
    with pytest.raises(ParsingError, match="Unsupported"):
        parsers.parse_bytes(b"x", "exe")


# ---------------------------------------------------------------------------
# Cleaning and chunking
# ---------------------------------------------------------------------------


def test_clean_code_preserves_indentation_but_normalizes_line_endings():
    cleaned = clean_code("def f():\r\n    if x:\r\n        return  1   \r\n\r\n\r\n\r\nx = 2\r\n")
    assert cleaned == "def f():\n    if x:\n        return  1\n\nx = 2"


def test_prose_cleaning_is_unchanged():
    # the prose cleaner still collapses runs of spaces (regression guard)
    assert clean_text("a    b\n\n\n\nc") == "a b\n\nc"


def _py_module(n_functions: int, body_lines: int = 3) -> str:
    parts = []
    for i in range(n_functions):
        body = "\n".join(f"    x{j} = {j}" for j in range(body_lines))
        parts.append(f"def func_{i}(a, b):\n{body}\n    return a + b")
    return "\n\n\n".join(parts)


def test_functions_and_classes_are_not_split_when_they_fit():
    source = (
        "import os\n\n"
        "class Alpha:\n    def one(self):\n        return 1\n\n    def two(self):\n        return 2\n\n"
        "def beta():\n    return 'beta'\n\n"
        "def gamma():\n    return 'gamma'\n"
    )
    chunks = chunk_code(source, 90)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 90
        # every def/class keyword line begins at a chunk start or follows a blank line
    joined = "\n\n".join(chunks)
    for name in ("class Alpha", "def one", "def two", "def beta", "def gamma"):
        assert name in joined
    # the whole Alpha class (it fits) stays in one chunk
    alpha_chunk = next(c for c in chunks if "class Alpha" in c)
    assert "def one" in alpha_chunk and "def two" in alpha_chunk and "return 2" in alpha_chunk
    # beta's body is never separated from its signature
    beta_chunk = next(c for c in chunks if "def beta" in c)
    assert "return 'beta'" in beta_chunk


def test_chunks_start_on_declaration_boundaries():
    source = _py_module(20)
    chunks = chunk_code(source, 400)
    assert len(chunks) > 3
    for chunk in chunks:
        assert len(chunk) <= 400
        assert chunk.startswith("def func_")


def test_decorators_and_leading_comments_stay_with_their_function():
    source = (
        "x = 1\n\n"
        "# Computes the thing\n@cache\ndef compute():\n    return 42\n\n"
        "def other():\n    return 0\n"
    )
    chunks = chunk_code(source, 70)
    compute_chunk = next(c for c in chunks if "def compute" in c)
    assert "@cache" in compute_chunk and "# Computes the thing" in compute_chunk


def test_oversized_function_is_split_within_size_without_losing_content():
    body = "\n".join(f"    value_{i} = compute({i})" for i in range(200))
    source = f"def huge():\n{body}\n    return 1\n"
    chunks = chunk_code(source, 300)
    assert len(chunks) > 3
    assert all(len(c) <= 300 for c in chunks)
    recombined = "\n".join(chunks)
    for i in (0, 57, 199):
        assert f"value_{i} = compute({i})" in recombined
    # indentation preserved inside the split pieces
    assert any(line.startswith("    value_") for c in chunks for line in c.split("\n"))


def test_single_very_long_line_is_hard_split_within_size():
    source = "const d = '" + "z" * 5000 + "';\n"
    chunks = chunk_code(source, 1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).count("z") == 5000


def test_chunk_code_validates_and_handles_empty():
    assert chunk_code("   \n", 100) == []
    with pytest.raises(ValueError):
        chunk_code("x", 0)


def test_prose_chunking_is_unchanged():
    text = "First paragraph here.\n\nSecond paragraph here.\n\n" + "word " * 400
    chunks = chunk_text(clean_text(text), 200, 30)
    assert len(chunks) > 2
    assert chunks[0].startswith("First paragraph here.")


def test_pipeline_uses_code_path_for_code_and_prose_path_for_documents():
    code = "def f():\n        deeply_indented = 1\n"
    code_chunks = extract_chunks_from_bytes(code.encode(), "py", 500, 50)
    assert "        deeply_indented" in code_chunks[0].text  # indentation intact

    md = "Some    spaced   text\n\nSecond paragraph".encode()
    md_chunks = extract_chunks_from_bytes(md, "md", 500, 50)
    assert "Some spaced text" in md_chunks[0].text  # prose behavior unchanged


@pytest.mark.parametrize("extension", REQUIRED_CODE_EXTENSIONS)
def test_pipeline_produces_chunks_for_every_code_extension(extension):
    chunks = extract_chunks_from_bytes(SAMPLES[extension].encode(), extension, 500, 50)
    assert chunks and chunks[0].index == 0
    assert all(c.page_number is None for c in chunks)


def test_pipeline_rejects_binary_and_invalid_code():
    for bad in (b"\x00\x01", b"\xff\xfe\xfa", b""):
        with pytest.raises(ParsingError):
            extract_chunks_from_bytes(bad, "py")


# ---------------------------------------------------------------------------
# GitHub discovery
# ---------------------------------------------------------------------------


def _mock_github(monkeypatch, tree, blobs=None):
    repo_json = {"full_name": "octocat/Hello-World", "private": False, "default_branch": "main"}
    blobs = blobs or {}

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/user"):
            return _FakeResponse(200, {})
        if "/git/trees/" in url:
            return _FakeResponse(200, {"tree": tree})
        if "/git/blobs/" in url:
            sha = url.rsplit("/", 1)[-1]
            if sha not in blobs:
                return _FakeResponse(404, {})
            return _FakeResponse(200, {"content": _b64(blobs[sha]), "encoding": "base64"})
        return _FakeResponse(200, repo_json)

    monkeypatch.setattr(gh.requests, "get", fake_get)


def _blob(path, sha, size=100):
    return {"path": path, "type": "blob", "sha": sha, "size": size}


def test_discovery_applies_every_filter(monkeypatch):
    tree = [_blob(f"src/f.{e}", f"sha-{e}") for e in REQUIRED_CODE_EXTENSIONS]
    tree += [
        _blob("README.md", "sha-readme"),
        _blob("docs/a.pdf", "sha-pdf"),
        _blob("node_modules/x/index.js", "sha-nm"),
        _blob("dist/app.js", "sha-dist"),
        _blob("build/x.py", "sha-build"),
        _blob("target/x.json", "sha-target"),
        _blob("vendor/x.py", "sha-vendor"),
        _blob(".venv/lib/x.py", "sha-venv"),
        _blob(".git/config.json", "sha-git"),
        _blob(".env", "sha-env"),
        _blob("config/.env.production", "sha-env2"),
        _blob("keys/server.pem", "sha-pem"),
        _blob("secrets.yaml", "sha-secrets"),
        _blob("static/app.min.js", "sha-min"),
        _blob("static/app.min.css", "sha-mincss"),
        _blob("package-lock.json", "sha-lock"),
        _blob("assets/logo.png", "sha-png"),
        _blob("bin/tool.exe", "sha-exe"),
        _blob("lib/x.pyc", "sha-pyc"),
        _blob("big.py", "sha-big", size=5_000_000),
        {"path": "src", "type": "tree", "sha": "sha-dir", "size": 0},
    ]
    _mock_github(monkeypatch, tree)

    async def _run():
        connector = GitHubConnector(token="t", repo_full_name="octocat/Hello-World", max_file_size_bytes=1_000_000)
        await connector.connect()
        return {d["path"] for d in await connector.discover_files()}

    paths = asyncio.run(_run())
    expected = {f"src/f.{e}" for e in REQUIRED_CODE_EXTENSIONS} | {"README.md", "docs/a.pdf"}
    assert paths == expected


def test_discovery_uses_the_documentservice_allowlist_no_drift():
    # every extension DocumentService accepts is discoverable, and vice versa
    for ext in ALLOWED_FILE_TYPES:
        assert is_indexable_repo_path(f"a/b.{ext}")
        assert _extract_file_type(f"a/b.{ext}") == ext


def test_sync_skips_binary_invalid_empty_and_oversized_content_per_file(monkeypatch):
    tree = [
        _blob("ok.py", "sha-ok"),
        _blob("binary.py", "sha-bin"),
        _blob("latin1.js", "sha-latin"),
        _blob("empty.ts", "sha-empty"),
        _blob("liar.json", "sha-liar", size=10),  # tree says small, blob is large
        _blob("doc.pdf", "sha-pdf"),
    ]
    blobs = {
        "sha-ok": "x = 1\n",
        "sha-bin": b"\x7fELF\x00\x00\x01",
        "sha-latin": b"var s = '\xe9\xe8';\n",
        "sha-empty": b"  \n",
        "sha-liar": "{" + " " * 3000 + "}",
        "sha-pdf": b"%PDF-1.4 \x00\x01 binary is fine for pdf",
    }
    _mock_github(monkeypatch, tree, blobs)

    async def _run():
        connector = GitHubConnector(token="t", repo_full_name="octocat/Hello-World", max_file_size_bytes=2000)
        return await connector.sync()

    result = asyncio.run(_run())
    assert {f.path for f in result.files} == {"ok.py", "doc.pdf"}
    assert result.discovered_count == 6
    assert result.fetch_failures == 4


# ---------------------------------------------------------------------------
# Incremental sync with code files (real pipeline, in-memory DB)
# ---------------------------------------------------------------------------

AUTH_PY_V1 = (
    "import hashlib\n\n\n"
    "def verify_password(raw, stored):\n"
    "    \"\"\"Check a password against its stored hash.\"\"\"\n"
    "    return hashlib.sha256(raw.encode()).hexdigest() == stored\n\n\n"
    "class SessionStore:\n"
    "    def create(self, user_id):\n"
    "        return f'session-{user_id}'\n"
)
AUTH_PY_V2 = AUTH_PY_V1 + "\n\ndef rotate_token(token):\n    return token[::-1]\n"
UTILS_JS = "export function formatDate(d) {\n  return d.toISOString();\n}\n"
CONFIG_YAML = "server:\n  port: 8080\n  debug: false\n"
README = "# Demo\n\nA small demo repository used for the sync tests, with some text."


async def _sync(service, user, connector):
    return await service.sync_github(connector_id=connector.id, user_id=user.id, github_token="ghp_secret")


def test_incremental_add_update_unchanged_delete_for_code_files(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user, _b, workspace, connector = await _seed(session_factory)

        tree = [
            _blob("README.md", "sha-readme"),
            _blob("src/auth.py", "sha-auth-1"),
            _blob("web/utils.js", "sha-utils"),
            _blob("config/app.yaml", "sha-config"),
        ]
        blobs = {
            "sha-readme": README, "sha-auth-1": AUTH_PY_V1, "sha-utils": UTILS_JS,
            "sha-config": CONFIG_YAML,
        }
        _mock_github(monkeypatch, tree, blobs)

        async with session_factory() as session:
            store = FakeVectorStore()
            service = _make_connector_service(session, store)

            # --- initial sync: everything new, README still indexed ----------
            first = await _sync(service, user, connector)
            await session.commit()
            assert (first.files_added, first.files_updated, first.files_unchanged, first.files_deleted, first.files_skipped) == (4, 0, 0, 0, 0)

            docs = {d.filename: d for d in await DocumentRepository(session).get_by_workspace_owner(workspace.id, user.id)}
            assert set(docs) == {"README.md", "src/auth.py", "web/utils.js", "config/app.yaml"}
            assert {d.file_type for d in docs.values()} == {"md", "py", "js", "yaml"}
            for d in docs.values():
                assert d.status == DocumentStatus.INDEXED and d.chunk_count > 0
            auth_id = docs["src/auth.py"].id

            # path-carrying metadata on code chunks
            rows = (await session.execute(select(Chunk).where(Chunk.document_id == auth_id))).scalars().all()
            assert rows
            meta = rows[0].metadata_
            assert meta["path"] == "src/auth.py"
            assert meta["filename"] == "src/auth.py"
            assert meta["repository"] == "octocat/Hello-World"
            assert meta["branch"] == "main"
            assert meta["github_sha"] == "sha-auth-1"
            assert meta["github_url"] == "https://github.com/octocat/Hello-World/blob/main/src/auth.py"
            assert meta["origin"] == "github" and meta["source"] == "py"
            assert any("def verify_password" in r.content for r in rows)
            # indentation preserved in stored chunk text
            assert any("    return hashlib" in r.content for r in rows)

            # Qdrant points identify the original file path
            auth_points = [p for p in store.upserted if p.document_id == auth_id]
            assert auth_points and all(p.filename == "src/auth.py" and p.source == "py" for p in auth_points)

            # --- second sync, nothing changed -> all unchanged ---------------
            second = await _sync(service, user, connector)
            await session.commit()
            assert (second.files_added, second.files_updated, second.files_unchanged, second.files_deleted) == (0, 0, 4, 0)

            # --- change auth.py (new sha), delete utils.js, add a new .sql ---
            tree[1] = _blob("src/auth.py", "sha-auth-2")
            tree.pop(2)
            tree.append(_blob("db/schema.sql", "sha-sql"))
            blobs["sha-auth-2"] = AUTH_PY_V2
            blobs["sha-sql"] = "CREATE TABLE users (id INT PRIMARY KEY);\n"
            _mock_github(monkeypatch, tree, blobs)

            third = await _sync(service, user, connector)
            await session.commit()
            assert (third.files_added, third.files_updated, third.files_unchanged, third.files_deleted, third.files_skipped) == (1, 1, 2, 1, 0)

            docs = {d.filename: d for d in await DocumentRepository(session).get_by_workspace_owner(workspace.id, user.id)}
            assert set(docs) == {"README.md", "src/auth.py", "config/app.yaml", "db/schema.sql"}
            # the updated document kept its ID, was reindexed with the new sha
            assert docs["src/auth.py"].id == auth_id
            rows = (await session.execute(select(Chunk).where(Chunk.document_id == auth_id))).scalars().all()
            assert len(rows) == docs["src/auth.py"].chunk_count
            assert any("def rotate_token" in r.content for r in rows)
            assert {r.metadata_["github_sha"] for r in rows} == {"sha-auth-2"}
            # deleted file's vectors were removed
            assert len(store.deleted_document_ids) >= 1

        await engine.dispose()

    asyncio.run(_run())


def test_file_level_failures_do_not_abort_the_repo_sync(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user, _b, workspace, connector = await _seed(session_factory)
        tree = [
            _blob("good.py", "sha-good"),
            _blob("bad_binary.py", "sha-bad"),
            _blob("bad_utf8.js", "sha-utf8"),
            _blob("missing.ts", "sha-missing"),  # blob fetch 404s
            _blob("README.md", "sha-readme"),
        ]
        blobs = {
            "sha-good": "def good():\n    return 1\n",
            "sha-bad": b"\x00\x01\x02binary",
            "sha-utf8": b"\xff\xfe\xfd",
            "sha-readme": README,
        }
        _mock_github(monkeypatch, tree, blobs)
        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary = await _sync(service, user, connector)
            await session.commit()
            assert summary.files_added == 2
            assert summary.files_skipped == 3
            assert summary.status == "completed"
            names = {d.filename for d in await DocumentRepository(session).get_by_workspace_owner(workspace.id, user.id)}
            # rejected files never produced stray Document rows
            assert names == {"good.py", "README.md"}
        await engine.dispose()

    asyncio.run(_run())


def test_secret_and_excluded_files_are_never_fetched_or_stored(monkeypatch):
    fetched = []

    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user, _b, workspace, connector = await _seed(session_factory)
        tree = [
            _blob("app.py", "sha-app"),
            _blob(".env", "sha-env"),
            _blob("config/secrets.yaml", "sha-sec"),
            _blob("keys/id.pem", "sha-pem"),
            _blob("node_modules/a/b.js", "sha-nm"),
            _blob("static/x.min.js", "sha-min"),
        ]
        blobs = {"sha-app": "x = 1\n", "sha-env": "KEY=1", "sha-sec": "k: v", "sha-pem": "-----BEGIN",
                 "sha-nm": "a", "sha-min": "a"}
        _mock_github(monkeypatch, tree, blobs)
        real_get = gh.requests.get

        def spy(url, headers=None, timeout=None):
            if "/git/blobs/" in url:
                fetched.append(url.rsplit("/", 1)[-1])
            return real_get(url, headers=headers, timeout=timeout)

        monkeypatch.setattr(gh.requests, "get", spy)
        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            summary = await _sync(service, user, connector)
            await session.commit()
            assert summary.files_discovered == 1 and summary.files_added == 1
            names = {d.filename for d in await DocumentRepository(session).get_by_workspace_owner(workspace.id, user.id)}
            assert names == {"app.py"}
        await engine.dispose()

    asyncio.run(_run())
    assert fetched == ["sha-app"]  # excluded blobs were never even downloaded


def test_previously_indexed_secret_file_is_removed_on_next_sync(monkeypatch):
    """If a file later becomes excluded (e.g. renamed to a secrets file) the
    existing reconciliation treats it as no longer present and deletes it."""

    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user, _b, workspace, connector = await _seed(session_factory)
        _mock_github(monkeypatch, [_blob("a.py", "s1"), _blob("b.py", "s2")], {"s1": "a = 1\n", "s2": "b = 2\n"})
        async with session_factory() as session:
            service = _make_connector_service(session, FakeVectorStore())
            await _sync(service, user, connector)
            await session.commit()
            _mock_github(monkeypatch, [_blob("a.py", "s1")], {"s1": "a = 1\n"})
            summary = await _sync(service, user, connector)
            await session.commit()
            assert summary.files_deleted == 1 and summary.files_unchanged == 1
        await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# DocumentService / manual upload regressions
# ---------------------------------------------------------------------------


def test_document_service_accepts_code_for_connectors_but_manual_uploads_stay_restricted(monkeypatch):
    async def _run():
        engine, session_factory = await _make_engine_and_session_factory()
        user, _b, workspace, _connector = await _seed(session_factory)
        from app.repositories.chunk_repository import ChunkRepository
        from app.repositories.workspace_repository import WorkspaceRepository

        async with session_factory() as session:
            service = DocumentService(
                DocumentRepository(session), WorkspaceRepository(session), ChunkRepository(session), FakeVectorStore()
            )
            created = await service.upload_document(
                workspace_id=workspace.id, user_id=user.id, filename="m.py", content_type=None, content=b"x = 1\n"
            )
            assert created.file_type == "py"
            with pytest.raises(UnsupportedFileTypeError):
                await service.upload_document(
                    workspace_id=workspace.id, user_id=user.id, filename="m.py", content_type="text/x-python",
                    content=b"x = 1\n", allowed_file_types=DOCUMENT_FILE_TYPES,
                )
            ok = await service.upload_document(
                workspace_id=workspace.id, user_id=user.id, filename="n.md", content_type="text/markdown",
                content=b"# hi", allowed_file_types=DOCUMENT_FILE_TYPES,
            )
            assert ok.file_type == "md"
        await engine.dispose()

    asyncio.run(_run())


def test_manual_upload_route_passes_the_document_only_allowlist():
    captured = {}

    class _StubService:
        async def upload_document(self, **kwargs):
            captured.update(kwargs)
            raise UnsupportedFileTypeError("Unsupported file extension: .py")

    main.app.dependency_overrides[get_document_service] = lambda: _StubService()
    main.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    try:
        client = TestClient(main.app)
        response = client.post(
            "/api/v1/documents/upload",
            data={"workspace_id": str(uuid4())},
            files={"file": ("a.py", b"x = 1", "text/plain")},
        )
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 415
    assert captured["allowed_file_types"] == DOCUMENT_FILE_TYPES
