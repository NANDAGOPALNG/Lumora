"""Document file storage.

`app.storage.base`          - the StorageBackend interface and storage errors.
`app.storage.local_storage` - local filesystem storage (development, tests,
                              and every document stored before R2 support).
`app.storage.r2_storage`    - Cloudflare R2 (S3-compatible) object storage.
`app.storage.factory`       - picks the provider for new uploads, and the
                              provider that owns an existing document.

Nothing is imported eagerly here, so `import app.storage` never loads boto3.
"""
