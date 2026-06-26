from __future__ import annotations

import sys
from dataclasses import dataclass
from os import chdir
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from alembic.config import Config

from alembic import command

if TYPE_CHECKING:
    from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]
APP_IMPORT = "app.main:app"


@dataclass(frozen=True)
class UvicornConfig:
    app: str
    host: str
    port: int
    reload: bool


def should_run_migrations(settings: Settings) -> bool:
    return settings.run_migrations_on_startup


def build_uvicorn_config(settings: Settings) -> UvicornConfig:
    return UvicornConfig(
        app=APP_IMPORT,
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.server_reload,
    )


def run_migrations() -> None:
    alembic_config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def main() -> None:
    chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    from app.core.config import settings

    if should_run_migrations(settings):
        run_migrations()

    uvicorn_config = build_uvicorn_config(settings)
    uvicorn.run(
        uvicorn_config.app,
        host=uvicorn_config.host,
        port=uvicorn_config.port,
        reload=uvicorn_config.reload,
    )


if __name__ == "__main__":
    main()