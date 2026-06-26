from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DataOps Observability API"
    environment: str = "local"
    database_url: str = "sqlite:///./dataops_observability.db"
    api_prefix: str = "/api/v1"
    run_migrations_on_startup: bool = Field(
        default=False,
        description="Run Alembic migrations before starting the API process.",
    )
    server_host: str = Field(
        default="0.0.0.0",
        description="Host interface used by the production start script.",
    )
    server_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port used by the production start script.",
    )
    server_reload: bool = Field(
        default=False,
        description="Enable Uvicorn reload in the production start script.",
    )
    ingestion_api_keys: str = Field(
        default="",
        description="Comma-separated API keys accepted for write/ingestion endpoints.",
    )
    public_base_url: str = Field(
        default="http://127.0.0.1:8000",
        description="Base URL used in generated dashboard and API links.",
    )
    alert_webhook_urls: str = Field(
        default="",
        description="Comma-separated webhook URLs that receive operational alerts.",
    )
    alert_webhook_secret: str = Field(
        default="",
        description="Optional shared secret sent with webhook alert deliveries.",
    )
    alert_webhook_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        description="Timeout in seconds for outbound webhook alert deliveries.",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()