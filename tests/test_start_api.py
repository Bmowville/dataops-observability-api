from app.core.config import Settings
from scripts.start_api import APP_IMPORT, build_uvicorn_config, should_run_migrations


def test_build_uvicorn_config_uses_runtime_settings() -> None:
    settings = Settings(server_host="127.0.0.1", server_port=9000, server_reload=True)

    config = build_uvicorn_config(settings)

    assert config.app == APP_IMPORT
    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.reload is True


def test_should_run_migrations_is_opt_in() -> None:
    default_settings = Settings()
    migration_settings = Settings(run_migrations_on_startup=True)

    assert should_run_migrations(default_settings) is False
    assert should_run_migrations(migration_settings) is True