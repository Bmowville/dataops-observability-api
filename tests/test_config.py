import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (
            "postgres://user:password@db.example:5432/dataops?sslmode=require",
            "postgresql+psycopg://user:password@db.example:5432/dataops?sslmode=require",
        ),
        (
            "postgresql://user:password@db.example:5432/dataops",
            "postgresql+psycopg://user:password@db.example:5432/dataops",
        ),
    ],
)
def test_plain_postgres_database_urls_use_psycopg3(
    database_url: str,
    expected: str,
) -> None:
    assert Settings(database_url=database_url).database_url == expected


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user:password@db.example/dataops",
        "postgresql+asyncpg://user:password@db.example/dataops",
        "sqlite:///./dataops.db",
    ],
)
def test_driver_qualified_and_non_postgres_database_urls_are_unchanged(
    database_url: str,
) -> None:
    assert Settings(database_url=database_url).database_url == database_url


def test_production_requires_an_ingestion_api_key() -> None:
    with pytest.raises(ValidationError, match="INGESTION_API_KEYS must be configured"):
        Settings(environment="production", ingestion_api_keys=" , ")


def test_production_accepts_a_configured_ingestion_api_key() -> None:
    settings = Settings(environment="PRODUCTION", ingestion_api_keys="production-key")

    assert settings.ingestion_api_keys == "production-key"
