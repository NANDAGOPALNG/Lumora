"""Cloudflare R2 object storage (S3-compatible API).

boto3 is synchronous, so every call runs in a worker thread via
`asyncio.to_thread` and never blocks the event loop. boto3 clients are
thread-safe, so one client is shared by all requests.

Security:
- Credentials come only from settings (environment variables) and are
  passed straight to the boto3 client; they are never logged, stored on
  instances that get logged, or included in exception messages. Errors
  surface only the operation name and the S3 error code / exception type.
- Object keys are derived from the document UUID, never from client input.
"""

import asyncio
import logging
import re
from typing import Any, Callable, List, Optional
from uuid import UUID

from app.config.settings import Settings
from app.storage.base import (
    StorageBackend,
    StorageConfigurationError,
    StorageError,
    StorageNotFoundError,
    sanitize_extension,
)

logger = logging.getLogger(__name__)

R2_SCHEME = "r2://"
KEY_PREFIX = "documents/"

# Bounded network behaviour: fail fast rather than hang a request.
_CONNECT_TIMEOUT = 5  # seconds
_READ_TIMEOUT = 30  # seconds
_MAX_ATTEMPTS = 3  # boto3 "standard" retry mode, with its own backoff

_BUCKET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")
_MAX_KEY_LENGTH = 1024

_NOT_FOUND_CODES = {"NoSuchKey", "NotFound", "404"}

_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


def create_s3_client(*, endpoint_url: str, access_key_id: str, secret_access_key: str) -> Any:
    """Build the boto3 S3 client for R2 (a seam for tests; imports boto3 lazily)."""
    import boto3
    from botocore.config import Config

    config = Config(
        signature_version="s3v4",
        region_name="auto",  # R2 ignores regions; "auto" is its documented value
        # total_max_attempts counts the first try (plain "max_attempts" counts
        # only the retries after it), so this is exactly _MAX_ATTEMPTS tries.
        retries={"total_max_attempts": _MAX_ATTEMPTS, "mode": "standard"},
        connect_timeout=_CONNECT_TIMEOUT,
        read_timeout=_READ_TIMEOUT,
        s3={"addressing_style": "path"},
        # boto3 >= 1.36 adds CRC32 checksums by default, which R2 does not
        # support; only compute/validate them when an operation requires it.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=config,
    )


def _blank(value: Optional[str]) -> bool:
    return value is None or not value.strip()


def resolve_r2_config(settings: Settings) -> dict:
    """Validate R2 settings and return {endpoint_url, access_key_id,
    secret_access_key, bucket}.

    Raises StorageConfigurationError naming the missing/invalid environment
    variables - never their values.
    """
    missing: List[str] = []
    if _blank(settings.r2_access_key_id):
        missing.append("R2_ACCESS_KEY_ID")
    if _blank(settings.r2_secret_access_key):
        missing.append("R2_SECRET_ACCESS_KEY")
    if _blank(settings.r2_bucket_name):
        missing.append("R2_BUCKET_NAME")
    if _blank(settings.r2_endpoint_url) and _blank(settings.r2_account_id):
        missing.append("R2_ACCOUNT_ID (or R2_ENDPOINT_URL)")
    if missing:
        raise StorageConfigurationError(
            "Cloudflare R2 storage is selected but required settings are missing: "
            + ", ".join(missing)
        )

    bucket = settings.r2_bucket_name.strip()
    if not _BUCKET_NAME_RE.match(bucket):
        raise StorageConfigurationError(
            "R2_BUCKET_NAME is invalid: use 3-63 lowercase letters, digits or hyphens"
        )

    if not _blank(settings.r2_endpoint_url):
        endpoint = settings.r2_endpoint_url.strip().rstrip("/")
    else:
        account_id = settings.r2_account_id.strip()
        if not _ACCOUNT_ID_RE.match(account_id):
            raise StorageConfigurationError("R2_ACCOUNT_ID is invalid")
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    is_local_dev_endpoint = endpoint.startswith(("http://localhost", "http://127.0.0.1"))
    if not endpoint.startswith("https://") and not is_local_dev_endpoint:
        raise StorageConfigurationError("R2_ENDPOINT_URL must start with https://")

    return {
        "endpoint_url": endpoint,
        "access_key_id": settings.r2_access_key_id.strip(),
        "secret_access_key": settings.r2_secret_access_key.strip(),
        "bucket": bucket,
    }


def key_from_reference(storage_path: str) -> str:
    """Extract and validate the object key from an "r2://<key>" reference."""
    if not isinstance(storage_path, str) or not storage_path.startswith(R2_SCHEME):
        raise StorageError("Not an R2 storage reference")
    key = storage_path[len(R2_SCHEME):]
    if (
        not key
        or len(key) > _MAX_KEY_LENGTH
        or key.startswith("/")
        or "\\" in key
        or ".." in key.split("/")
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in key)
    ):
        raise StorageError("Invalid R2 storage reference")
    return key


class R2Storage(StorageBackend):
    name = "r2"

    def __init__(self, *, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "R2Storage":
        config = resolve_r2_config(settings)
        client = create_s3_client(
            endpoint_url=config["endpoint_url"],
            access_key_id=config["access_key_id"],
            secret_access_key=config["secret_access_key"],
        )
        return cls(client=client, bucket=config["bucket"])

    def __repr__(self) -> str:  # never include the client (it holds credentials)
        return "R2Storage()"

    def generate_storage_path(self, document_id: UUID, file_type: str) -> str:
        extension = sanitize_extension(file_type)
        name = f"{document_id}.{extension}" if extension else str(document_id)
        return f"{R2_SCHEME}{KEY_PREFIX}{name}"

    async def _call(self, operation: str, func: Callable[..., Any], **kwargs: Any) -> Any:
        """Run one blocking boto3 call in a worker thread, translating errors."""
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return await asyncio.to_thread(func, **kwargs)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", "Unknown"))
            if code in _NOT_FOUND_CODES:
                raise StorageNotFoundError(f"R2 {operation}: object not found") from exc
            raise StorageError(f"R2 {operation} failed: {code}") from exc
        except BotoCoreError as exc:
            # Timeouts, connection errors, missing credentials, ...
            raise StorageError(f"R2 {operation} failed: {type(exc).__name__}") from exc

    async def save(self, storage_path: str, content: bytes) -> None:
        key = key_from_reference(storage_path)
        extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
        await self._call(
            "upload",
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=_CONTENT_TYPES.get(extension, "application/octet-stream"),
        )

    async def read(self, storage_path: str) -> bytes:
        key = key_from_reference(storage_path)
        max_bytes = Settings.get_instance().max_document_size_bytes

        def _get_and_read(**kwargs: Any) -> bytes:
            response = self._client.get_object(**kwargs)
            body = response["Body"]
            try:
                declared = response.get("ContentLength")
                if isinstance(declared, int) and declared > max_bytes:
                    raise StorageError("R2 download refused: object exceeds the maximum document size")
                # Read at most one byte past the limit, then check, so an
                # object with a wrong/missing length can't exhaust memory.
                data = body.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise StorageError("R2 download refused: object exceeds the maximum document size")
                return data
            finally:
                body.close()

        return await self._call("download", _get_and_read, Bucket=self._bucket, Key=key)

    async def delete(self, storage_path: str) -> None:
        key = key_from_reference(storage_path)
        try:
            # S3 DeleteObject succeeds for a missing key; tolerate a 404 anyway.
            await self._call("delete", self._client.delete_object, Bucket=self._bucket, Key=key)
        except StorageNotFoundError:
            logger.info("R2 object already absent on delete: %s", key)

    async def exists(self, storage_path: str) -> bool:
        key = key_from_reference(storage_path)
        try:
            await self._call("exists check", self._client.head_object, Bucket=self._bucket, Key=key)
        except StorageNotFoundError:
            return False
        return True
