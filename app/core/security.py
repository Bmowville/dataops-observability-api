from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

INGESTION_API_KEY_HEADER = "X-DataOps-API-Key"

ingestion_api_key_header = APIKeyHeader(
    name=INGESTION_API_KEY_HEADER,
    auto_error=False,
)


def get_configured_ingestion_api_keys(settings: Settings) -> tuple[str, ...]:
    return tuple(
        api_key.strip()
        for api_key in settings.ingestion_api_keys.split(",")
        if api_key.strip()
    )


def require_ingestion_api_key(
    api_key: Annotated[str | None, Security(ingestion_api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    configured_keys = get_configured_ingestion_api_keys(settings)
    if not configured_keys:
        return

    if api_key is None or not any(compare_digest(api_key, key) for key in configured_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing ingestion API key",
        )