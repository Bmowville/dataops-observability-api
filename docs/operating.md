# Operating DataOps Observability API

This project can run as a self-hosted operational service. The sample data is only for evaluation; real usage comes from registering pipelines and sending pipeline run and quality-check events from scheduled jobs, Airflow, dbt, GitHub Actions, or custom ETL code.

## Local Evaluation

Use the local demo path when you want a populated dashboard quickly:

```powershell
python -m pip install -e ".[dev]"
python scripts/demo_setup.py
uvicorn app.main:app --reload
```

On Windows, the PowerShell helper can run the same setup and optionally start the API:

```powershell
.\scripts\demo.ps1
.\scripts\demo.ps1 -StartApi
```

The demo setup uses the default SQLite database and can be rerun to reset the sample pipelines, runs, quality checks, and alert delivery history.

## Self-Hosted Postgres Run

Docker Compose runs the API with Postgres, waits for the database to be healthy, and runs Alembic migrations before starting Uvicorn.

1. Create a local environment file:

```powershell
Copy-Item .env.example .env
```

2. Edit `.env` before exposing the service:

```dotenv
POSTGRES_PASSWORD=replace-with-a-strong-password
INGESTION_API_KEYS=replace-with-a-long-random-key
PUBLIC_BASE_URL=https://dataops.example.com
ALERT_WEBHOOK_URLS=https://hooks.example.com/dataops
ALERT_WEBHOOK_SECRET=replace-with-a-shared-webhook-secret
```

3. Start the service:

```powershell
docker compose up --build -d
```

4. Verify it is healthy:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/health"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/metrics/summary"
```

Open:

- Dashboard: `http://127.0.0.1:8000/dashboard`
- API docs: `http://127.0.0.1:8000/docs`
- Operations overview: `http://127.0.0.1:8000/api/v1/metrics/operations-overview?stale_after_minutes=60`
- Prometheus-style metrics: `http://127.0.0.1:8000/api/v1/metrics/prometheus`

## Ingest Real Pipeline Events

When `INGESTION_API_KEYS` is set, write endpoints require `X-DataOps-API-Key`.

Register a pipeline once:

```powershell
$headers = @{
  "Content-Type" = "application/json"
  "X-DataOps-API-Key" = $env:DATAOPS_API_KEY
}

$pipeline = @{
  name = "daily_orders_load"
  owner = "Data Platform"
  source_system = "warehouse"
  expected_cadence_minutes = 1440
  stale_after_minutes = 90
  alert_severity = "high"
  runbook_url = "https://runbooks.example.com/orders-daily-load"
} | ConvertTo-Json

Invoke-RestMethod "http://127.0.0.1:8000/api/v1/pipelines" -Method Post -Headers $headers -Body $pipeline
```

Report a run from a scheduled job:

```powershell
$run = @{
  name = "daily_orders_load"
  source_system = "warehouse"
  status = "running"
  records_processed = 0
} | ConvertTo-Json

Invoke-RestMethod "http://127.0.0.1:8000/api/v1/pipeline-runs" -Method Post -Headers $headers -Body $run
```

See `examples/integrations/` and [integrations.md](integrations.md) for Python, GitHub Actions, Airflow, and dbt examples.

## Alerts

Set `ALERT_WEBHOOK_URLS` to one or more Slack-compatible bridges, incident tools, or internal webhook receivers. The service sends alerts for:

- failed or canceled pipeline runs
- failed or warning quality checks

Delivery attempts are stored in Postgres and can be audited:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/alerts/deliveries?limit=20"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/alerts/deliveries/latest"
```

## Backups

The Compose setup stores Postgres data in the `postgres_data` volume. Back up the database before upgrades:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T db pg_dump -U dataops dataops_observability > backups\dataops_observability.sql
```

Restore into a fresh database with:

```powershell
Get-Content backups\dataops_observability.sql | docker compose exec -T db psql -U dataops dataops_observability
```

If you change `POSTGRES_USER` or `POSTGRES_DB`, use those values in the backup and restore commands.

## Upgrades

1. Back up Postgres.
2. Pull or build the new image.
3. Run `docker compose up --build -d`.
4. The API container runs Alembic migrations before Uvicorn starts.
5. Check `/health`, `/api/v1/metrics/summary`, and the dashboard.

For environments with stricter release controls, set `RUN_MIGRATIONS_ON_STARTUP=false`, run `alembic upgrade head` as a separate deployment step, then start the API container.

## Production Notes

- Put the API behind TLS with a reverse proxy or platform ingress.
- Set strong `INGESTION_API_KEYS` and rotate them with comma-separated old/new values during transitions.
- Store real passwords and webhook secrets in a secret manager or deployment platform, not in source control.
- Restrict Postgres network access to the API service.
- Monitor `/health`, `/api/v1/metrics/prometheus`, and alert delivery failures.
- Keep regular Postgres backups before image upgrades or schema migrations.