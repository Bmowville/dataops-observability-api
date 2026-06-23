import tomllib
from pathlib import Path

from app import __version__
from app.main import app


def test_app_version_matches_project_metadata() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert __version__ == pyproject["project"]["version"]
    assert app.version == __version__