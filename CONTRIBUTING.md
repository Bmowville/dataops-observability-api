# Contributing

Thanks for helping improve DataOps Observability API.

## Local setup

Use Python 3.11 or newer in a virtual environment:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev,postgres]"
```

The default configuration uses SQLite. Apply migrations before starting the API:

```bash
alembic upgrade head
python scripts/start_api.py
```

For PostgreSQL development, set `DATABASE_URL` to a SQLAlchemy psycopg URL or use the provided
Docker Compose stack.

## Quality checks

Run the same checks required by CI before opening a pull request:

```bash
ruff check .
mypy app
python -m pytest
docker build --tag dataops-observability-api:local .
```

The test command enforces at least 85% branch coverage across `app` and `scripts` and writes a
Cobertura-compatible `coverage.xml` report.

If a model or schema changes, add an Alembic revision and verify a clean database can migrate to
the latest head. Do not commit local databases, environment files, credentials, or API keys.

## Pull requests

- Keep each pull request focused and explain the user-visible or operational impact.
- Add or update tests for behavior changes.
- Update documentation when configuration or public API behavior changes.
- Use clear commit messages and link the relevant issue when one exists.
- Confirm CI is green and resolve review feedback before requesting merge.

For sensitive findings, follow `SECURITY.md` instead of opening a public issue.
