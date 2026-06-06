# DataOps Observability API

A FastAPI service for tracking data pipeline runs, quality checks, and operational status.

The service keeps operational metadata for data workflows in a small API surface with typed routes, database migrations, test coverage, Docker support, and CI quality gates.

## Service Scope

- FastAPI application structure with versioned API routes
- SQLAlchemy 2.0 models and session management
- Alembic database migrations
- Pydantic request and response schemas
- Service-layer functions separated from route handlers
- Health checks with database connectivity
- Pytest tests using dependency overrides and isolated SQLite state
- Ruff, mypy, and GitHub Actions CI
- Dockerfile and Compose setup for local service runs

## Domain

The API tracks operational metadata for data workflows:

- Pipeline runs: source system, status, timing, records processed, and errors
- Quality checks: check name, severity, status, expected value, observed value, and details
- Summary metrics: run counts and failing quality checks

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Open:

- API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

## Run Quality Gates

```powershell
ruff check .
mypy app
alembic upgrade head
pytest
```

## Example Requests

Create a pipeline run:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline-runs \
  -H "Content-Type: application/json" \
  -d '{"name":"daily_orders_load","source_system":"warehouse","status":"running","records_processed":0}'
```

Add a quality check:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline-runs/1/quality-checks \
  -H "Content-Type: application/json" \
  -d '{"check_name":"row_count_minimum","status":"passed","severity":"high","expected_value":"1000+","observed_value":"1284"}'
```

## Docker

```bash
docker compose up --build
```

The container starts the FastAPI app on port `8000`. Run migrations before production deployment.

## API Surface

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Service and database health |
| POST | `/api/v1/pipeline-runs` | Create a pipeline run |
| GET | `/api/v1/pipeline-runs` | List pipeline runs, optionally filtered by status |
| GET | `/api/v1/pipeline-runs/{run_id}` | Read one pipeline run |
| PATCH | `/api/v1/pipeline-runs/{run_id}` | Update run status/details |
| POST | `/api/v1/pipeline-runs/{run_id}/quality-checks` | Add a quality check to a run |
| GET | `/api/v1/pipeline-runs/{run_id}/quality-checks` | List quality checks for a run |
| GET | `/api/v1/metrics/summary` | Operational summary counts |

## Configuration

Settings are loaded from environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `DataOps Observability API` | FastAPI application name |
| `ENVIRONMENT` | `local` | Environment label returned by health checks |
| `DATABASE_URL` | `sqlite:///./dataops_observability.db` | SQLAlchemy database URL |
| `API_PREFIX` | `/api/v1` | Versioned API prefix |

## Notes

SQLite is the default for local development. The SQLAlchemy and Alembic setup is structured so the service can be moved to Postgres by changing `DATABASE_URL` and adding the relevant deployment configuration.