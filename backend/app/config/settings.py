from pydantic_settings import BaseSettings
from typing import Optional
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

    # External services
    openai_api_key: Optional[str] = None

    # Environment
    environment: Environment = Environment.DEVELOPMENT

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "case_sensitive": False,
    }

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