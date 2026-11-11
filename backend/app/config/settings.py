from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import List, Optional
from enum import Enum

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
    document_storage_path: str = "storage/documents"
    max_document_size_mb: int = 20

    # Ingestion / chunking
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # Embeddings
    embedding_model_name: str = "jina-embeddings-v3"
    embedding_batch_size: int = 32

    # Jina AI (remote Embeddings API – replaces local BGE-M3)
    jina_api_key: Optional[str] = None
    jina_embedding_url: str = "https://api.jina.ai/v1/embeddings"

    # Reranking
    reranker_model_name: str = "BAAI/bge-reranker-base"

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
    cors_origins: str = "http://localhost:3000"

    # Environment
    environment: Environment = Environment.DEVELOPMENT

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "case_sensitive": False,
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
        return self

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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