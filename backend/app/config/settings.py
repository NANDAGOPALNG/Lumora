from pydantic import Field, model_validator
from pydantic_settings import BaseSettings
from typing import List, Optional
from enum import Enum

# Development default. Production must set CORS_ORIGINS explicitly (enforced
# by Settings._validate_production_settings).
_DEFAULT_CORS_ORIGINS = "http://localhost:3000"


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

class Settings(BaseSettings):
    app_name: str = "Lumora API"
    app_version: str = "1.0.0"
    app_description: str = "Enterprise AI Knowledge Platform"

    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000

    # Security
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Google OAuth
    google_client_id: str

    # Database
    database_url: Optional[str] = None

    # Document storage
    # "local" (default; development and tests) or "r2" (Cloudflare R2).
    # Selects where NEW uploads are written. Existing documents are always
    # read from the provider that owns their storage_path (see app.storage).
    document_storage_backend: str = "local"
    document_storage_path: str = "storage/documents"  # local backend only
    max_document_size_mb: int = 20

    # Cloudflare R2 (S3-compatible). Only needed when
    # DOCUMENT_STORAGE_BACKEND=r2. The two credentials are excluded from
    # repr() so they can't leak through a logged Settings object.
    r2_account_id: Optional[str] = None
    r2_access_key_id: Optional[str] = Field(default=None, repr=False)
    r2_secret_access_key: Optional[str] = Field(default=None, repr=False)
    r2_bucket_name: Optional[str] = None
    # Optional; defaults to https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
    r2_endpoint_url: Optional[str] = None

    # Ingestion / chunking
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # Embeddings
    embedding_model_name: str = "jina-embeddings-v3"
    embedding_batch_size: int = 32

    # Jina AI (remote Embeddings API; no local model is loaded)
    jina_api_key: Optional[str] = None
    jina_embedding_url: str = "https://api.jina.ai/v1/embeddings"

    # Jina AI (remote Reranker API; no local model is loaded).
    # Reuses jina_api_key above; no second key is needed.
    jina_reranker_model_name: str = "jina-reranker-v2-base-multilingual"
    jina_reranker_url: str = "https://api.jina.ai/v1/rerank"

    # Qdrant
    qdrant_url: Optional[str] = None
    qdrant_api_key: Optional[str] = None

    # External services
    openai_api_key: Optional[str] = None

    # LLM generation (Gemini)
    gemini_api_key: Optional[str] = None
    gemini_model_name: str = "gemini-3.6-flash"

    # CORS: comma-separated list of allowed browser origins (e.g. the
    # Next.js frontend). Empty in production unless explicitly set.
    cors_origins: str = _DEFAULT_CORS_ORIGINS

    # Environment
    environment: Environment = Environment.DEVELOPMENT

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "case_sensitive": False,
        # A failed validation must never echo the offending input back: it
        # would print the start of SECRET_KEY / DATABASE_URL / API keys into
        # the host's logs. Errors still name the variable that is wrong.
        "hide_input_in_errors": True,
    }

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        """Fail fast at startup on unsafe production configuration,
        rather than at the first request that needs the setting."""
        if self.environment == Environment.PRODUCTION:
            if not self.database_url:
                raise ValueError("DATABASE_URL must be set in production")
            if len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")

            # Fail at startup, naming the variables (never their values),
            # instead of on the first upload / search / chat request.
            missing = [
                name
                for name, value in (
                    ("JINA_API_KEY", self.jina_api_key),
                    ("QDRANT_URL", self.qdrant_url),
                    ("QDRANT_API_KEY", self.qdrant_api_key),
                    ("GEMINI_API_KEY", self.gemini_api_key),
                )
                if not (value or "").strip()
            ]
            if missing:
                raise ValueError(f"{', '.join(missing)} must be set in production")

            # Render Free (and similar hosts) wipe the local disk on every
            # deploy, restart and spin-down, so uploads must go to R2. The
            # R2_* credentials themselves are checked at startup by
            # app.storage.factory.validate_storage_configuration().
            if (self.document_storage_backend or "").strip().lower() != "r2":
                raise ValueError("DOCUMENT_STORAGE_BACKEND must be 'r2' in production")

            if self.cors_origins == _DEFAULT_CORS_ORIGINS:
                raise ValueError(
                    "CORS_ORIGINS must be set explicitly in production "
                    "(the deployed frontend origin, e.g. https://your-app.vercel.app)"
                )
            if "*" in self.cors_origin_list or not self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must list explicit origins in production, not '*'")
        return self

    @property
    def cors_origin_list(self) -> List[str]:
        # Browsers send the Origin header without a trailing slash, so a value
        # pasted as "https://app.example.com/" would otherwise never match.
        origins = (o.strip().rstrip("/") for o in self.cors_origins.split(","))
        return [o for o in origins if o]

    def get_database_url(self) -> Optional[str]:
        if self.database_url:
            return self.database_url
        elif self.environment != Environment.PRODUCTION:
            return f"sqlite+aiosqlite:///./lumora_{self.environment}.db"
        else:
            raise ValueError("DATABASE_URL must be set in production")

    @property
    def max_document_size_bytes(self) -> int:
        return self.max_document_size_mb * 1024 * 1024

    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    def configure_logging(self) -> None:
        import logging

        if self.is_production():
            logging.basicConfig(level=logging.WARNING)
        elif self.is_development():
            logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        else:
            logging.basicConfig(level=logging.DEBUG)

    @classmethod
    def get_instance(cls) -> "Settings":
        return cls()