import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("database_url", "expected_success"),
    [
        ("sqlite:///:memory:", False),
        ("postgresql://user:password@db.example/dataops?sslmode=require", True),
    ],
)
def test_serverless_entrypoint_requires_postgresql(
    database_url: str, expected_success: bool
) -> None:
    environment = os.environ.copy()
    environment.update(
        DATABASE_URL=database_url,
        ENVIRONMENT="production",
        INGESTION_API_KEYS="serverless-entrypoint-test-key",
    )
    result = subprocess.run(
        [sys.executable, "-c", "from app.vercel import app; assert app.title"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert (result.returncode == 0) == expected_success, result.stderr
    if not expected_success:
        assert "require a PostgreSQL DATABASE_URL" in result.stderr
