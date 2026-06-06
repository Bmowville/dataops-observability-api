from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.pipeline_runs import router as pipeline_runs_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Track pipeline runs, quality checks, and data operations health.",
    )
    app.include_router(health_router)
    app.include_router(pipeline_runs_router, prefix=settings.api_prefix)
    return app


app = create_app()