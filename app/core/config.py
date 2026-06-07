from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DataOps Observability API"
    environment: str = "local"
    database_url: str = "sqlite:///./dataops_observability.db"
    api_prefix: str = "/api/v1"
    ingestion_api_keys: str = Field(
        default="",
        description="Comma-separated API keys accepted for write/ingestion endpoints.",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()