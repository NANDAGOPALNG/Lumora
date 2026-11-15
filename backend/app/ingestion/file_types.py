"""Single source of truth for which file types Lumora ingests, and which
repository paths must never be indexed.

Dependency-free on purpose (no app imports), so both the GitHub connector
and DocumentService can import it at module level without a circular
import.
"""

from typing import Optional

# Prose/document formats (pre-existing behavior; unchanged).
DOCUMENT_FILE_TYPES = frozenset({"pdf", "docx", "txt", "md"})

# Source-code / config / markup text files, all read by one shared
# UTF-8 text parser (see parsers/code_parser.py).
CODE_FILE_TYPES = frozenset(
    {
        "py",
        "js", "jsx", "mjs", "cjs",
        "ts", "tsx",
        "html",
        "css", "scss",
        "json",
        "yaml", "yml",
        "toml",
        "xml",
        "sql",
        "sh",
        "rst",
    }
)

ALLOWED_FILE_TYPES = DOCUMENT_FILE_TYPES | CODE_FILE_TYPES

# Directories that hold dependencies, build output or tooling state.
EXCLUDED_PATH_SEGMENTS = frozenset(
    {
        ".git", "node_modules", "vendor", "dist", "build", "target",
        "__pycache__", ".venv", "venv", ".idea", ".vscode",
        ".next", ".nuxt", ".cache", ".tox", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".gradle", "coverage", "bower_components",
        "site-packages", ".terraform", ".svn", ".hg",
    }
)

# Exact basenames (lower-case) that are lockfiles / generated manifests.
_GENERATED_FILENAMES = frozenset(
    {
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
        "uv.lock", "cargo.lock", "composer.lock", "gemfile.lock",
        "pipfile.lock", "npm-shrinkwrap.json",
    }
)

# Exact basenames (lower-case) that hold credentials or keys.
_SECRET_FILENAMES = frozenset(
    {
        ".env", ".netrc", ".npmrc", ".pypirc", ".htpasswd", ".pgpass",
        "credentials", "credentials.json", "credentials.yaml", "credentials.yml",
        "secrets.json", "secrets.yaml", "secrets.yml", "secrets.toml",
        "secret.json", "secret.yaml", "secret.yml", "secret.toml",
        "service-account.json", "service_account.json",
        "serviceaccount.json", "client_secret.json",
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
        "terraform.tfvars", "terraform.tfstate",
    }
)

_SECRET_EXTENSIONS = frozenset(
    {"pem", "key", "p12", "pfx", "jks", "keystore", "asc", "gpg", "ppk", "crt", "cer", "der"}
)

# Substrings in a basename that mark it as a secrets file
# (e.g. "my_secrets.yaml", "prod.credentials.json", "gcp-service-account-key.json").
# Only applied to config/data formats, where real secrets live, so prose
# docs such as docs/credentials-guide.md keep being indexed.
_SECRET_MARKER_EXTENSIONS = frozenset({"json", "yaml", "yml", "toml", "xml", "sh"})
_SECRET_NAME_MARKERS = ("secret", "credential", "private_key", "private-key", "service-account", "service_account")

# Sample/template env files are documentation, not secrets.
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".defaults")


def extract_extension(path: str) -> Optional[str]:
    """Lower-case extension of a path's basename, or None if it has none."""
    basename = path.rsplit("/", 1)[-1]
    if "." not in basename.lstrip("."):
        return None
    return basename.rsplit(".", 1)[-1].lower()


def is_excluded_directory_path(path: str) -> bool:
    """True if any directory component of `path` is an excluded directory."""
    directories = path.split("/")[:-1]
    return any(part.lower() in EXCLUDED_PATH_SEGMENTS for part in directories)


def is_secret_file(path: str) -> bool:
    """True for environment files, private keys and credential/secret files.

    `.env.example`-style templates are not secrets and are allowed (their
    extension is not in the allowlist anyway, so they are only indexed if
    they have an allowed extension).
    """
    basename = path.rsplit("/", 1)[-1].lower()

    if basename == ".env" or basename.startswith(".env."):
        return not basename.endswith(_ENV_TEMPLATE_SUFFIXES)
    if basename.endswith(".env"):
        return True
    if basename in _SECRET_FILENAMES:
        return True
    extension = extract_extension(path)
    if extension in _SECRET_EXTENSIONS:
        return True
    if extension in _SECRET_MARKER_EXTENSIONS and any(
        marker in basename for marker in _SECRET_NAME_MARKERS
    ):
        return True
    return False


def is_minified_or_generated(path: str) -> bool:
    """True for minified assets, source maps, bundles and lockfiles."""
    basename = path.rsplit("/", 1)[-1].lower()
    if basename in _GENERATED_FILENAMES:
        return True
    return (
        ".min." in basename
        or basename.endswith((".map", ".bundle.js", ".chunk.js"))
    )


def is_indexable_repo_path(path: str) -> bool:
    """Whether a repository path should be considered for indexing at all
    (allowed extension, not in an excluded directory, not a secret, not
    minified/generated)."""
    if not path:
        return False
    if extract_extension(path) not in ALLOWED_FILE_TYPES:
        return False
    if is_excluded_directory_path(path):
        return False
    if is_secret_file(path) or is_minified_or_generated(path):
        return False
    return True
