from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.pipeline import HealthResponse, LivenessResponse

router = APIRouter(tags=["health"])


@router.get("/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    return LivenessResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
    )


@router.get("/health", response_model=HealthResponse)
def health(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
        database="ok",
    )
