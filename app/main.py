from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.alerts import router as alerts_router
from app.api.health import router as health_router
from app.api.pipeline_runs import router as pipeline_runs_router
from app.api.pipelines import router as pipelines_router
from app.core.config import settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
DASHBOARD_PATH = STATIC_DIR / "dashboard.html"


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Track pipeline runs, quality checks, and data operations health.",
    )
    app.include_router(health_router)
    app.include_router(alerts_router, prefix=settings.api_prefix)
    app.include_router(pipelines_router, prefix=settings.api_prefix)
    app.include_router(pipeline_runs_router, prefix=settings.api_prefix)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/dashboard")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(DASHBOARD_PATH)

    return app


app = create_app()