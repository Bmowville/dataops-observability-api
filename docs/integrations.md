# Integration Guide

DataOps Observability API is useful when pipeline runners report a small amount of structured status data into the service. The API does not need to run the pipeline itself. It records what happened, keeps quality-check context next to the run, and powers the dashboard from those records.

## Reporting Flow

1. Create a pipeline run when work starts.
2. Add one or more quality checks while the job runs or after validation finishes.
3. Patch the pipeline run to `succeeded`, `failed`, or `canceled` when work ends.
4. Open `/dashboard` or call `/api/v1/metrics/operations-overview` to see the operating state.

## API Key Ingestion

Local demos work without credentials. For a deployed service, set `INGESTION_API_KEYS` to a comma-separated list of accepted keys:

```powershell
$env:INGESTION_API_KEYS = "dev-ingest-key"
```

Then configure reporters with the matching client-side key and send it as `X-DataOps-API-Key` on write requests:

```powershell
$env:DATAOPS_API_KEY = "dev-ingest-key"
```

Read-only endpoints such as `/dashboard`, `/health`, and `/api/v1/metrics/*` remain open. Only ingestion writes require the header when keys are configured.

## Webhook Alerts

Webhook alerts turn ingested events into operator notifications. Configure one or more receivers with `ALERT_WEBHOOK_URLS`:

```powershell
$env:PUBLIC_BASE_URL = "https://dataops.example.com"
$env:ALERT_WEBHOOK_URLS = "https://hooks.example.com/dataops"
$env:ALERT_WEBHOOK_SECRET = "shared-secret"
```

The service sends alerts in the background after the API write succeeds. Alerts fire for:

- pipeline runs patched to `failed` or `canceled`
- quality checks created as `failed` or `warning`

Successful runs and passed checks are recorded without sending notifications.

Every configured receiver gets a JSON payload like this:

```json
{
  "event_type": "quality_check_failed",
  "severity": "critical",
  "message": "Quality check freshness_sla is failed for orders_daily_load.",
  "occurred_at": "2026-06-07T21:00:00+00:00",
  "pipeline_run": {
    "id": 42,
    "name": "orders_daily_load",
    "source_system": "airflow",
    "status": "running",
    "records_processed": 1284,
    "started_at": "2026-06-07T20:55:00+00:00",
    "finished_at": null,
    "error_message": null,
    "created_at": "2026-06-07T20:55:00+00:00",
    "updated_at": "2026-06-07T20:55:00+00:00"
  },
  "quality_check": {
    "id": 9,
    "pipeline_run_id": 42,
    "check_name": "freshness_sla",
    "status": "failed",
    "severity": "critical",
    "expected_value": "less than 2 hours",
    "observed_value": "4 hours",
    "details": "Warehouse table is stale.",
    "created_at": "2026-06-07T21:00:00+00:00"
  },
  "links": {
    "dashboard": "https://dataops.example.com/dashboard",
    "pipeline_run": "https://dataops.example.com/api/v1/pipeline-runs/42",
    "timeline": "https://dataops.example.com/api/v1/pipeline-runs/42/timeline"
  }
}
```

If `ALERT_WEBHOOK_SECRET` is set, deliveries include `X-DataOps-Webhook-Secret`. Receivers should verify that header before acting on an alert.

## Common Event Shapes

Create a run:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline-runs \
  -H "Content-Type: application/json" \
  -H "X-DataOps-API-Key: $DATAOPS_API_KEY" \
  -d '{"name":"orders_daily_load","source_system":"airflow","status":"running","records_processed":0}'
```

Add a quality check:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline-runs/1/quality-checks \
  -H "Content-Type: application/json" \
  -H "X-DataOps-API-Key: $DATAOPS_API_KEY" \
  -d '{"check_name":"row_count_minimum","status":"passed","severity":"high","expected_value":"1000+","observed_value":"1284"}'
```

Finish the run:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/pipeline-runs/1 \
  -H "Content-Type: application/json" \
  -H "X-DataOps-API-Key: $DATAOPS_API_KEY" \
  -d '{"status":"succeeded","records_processed":1284}'
```

## Example Integrations

The `examples/integrations` folder includes copy-paste starting points:

| File | Use case |
| --- | --- |
| `python_reporter.py` | Standard-library Python reporter for custom jobs and scheduled scripts |
| `dbt_run_results.py` | Parse `target/run_results.json` after `dbt build` and report model/test results |
| `airflow_dag.py` | Airflow DAG pattern that reports run start, checks, and completion |
| `github-actions-report.yml` | GitHub Actions workflow pattern for scheduled or manual data jobs |

## Python Job

Run the API locally, then send a sample job event:

```powershell
$env:DATAOPS_API_URL = "http://127.0.0.1:8000"
python examples/integrations/python_reporter.py
```

Use environment variables to change the reported job:

```powershell
$env:DATAOPS_PIPELINE_NAME = "billing_reconciliation"
$env:DATAOPS_SOURCE_SYSTEM = "nightly_script"
$env:DATAOPS_RECORDS_PROCESSED = "8432"
$env:DATAOPS_API_KEY = "dev-ingest-key"
python examples/integrations/python_reporter.py
```

## dbt

Run dbt, then report the generated result file:

```bash
dbt build
python examples/integrations/dbt_run_results.py target/run_results.json
```

The reporter creates one pipeline run and adds a quality check for each dbt result. Failed dbt results become failed quality checks and mark the pipeline run as failed.

## Airflow

Copy `examples/integrations/airflow_dag.py` into your Airflow DAGs folder and set `DATAOPS_API_URL` in the Airflow environment. If the API is protected, also set `DATAOPS_API_KEY` from your Airflow secrets or environment management. The DAG demonstrates the reporting shape without requiring the API to own scheduling or orchestration.

## GitHub Actions

Copy `examples/integrations/github-actions-report.yml` into `.github/workflows/` in the repository that owns the data job. Replace the placeholder job step with the actual pipeline command and point `DATAOPS_API_URL` at a reachable DataOps Observability API deployment.

For production use, store `DATAOPS_API_KEY` as a GitHub Actions secret and keep the API URL in repository variables or secrets instead of hard-coding deployment details.

## What This Enables

Once pipelines report this minimal status data, the dashboard and metrics endpoints can answer operational questions without searching logs:

- Which pipelines need attention right now?
- Which runs are stale or still active past the expected window?
- Which quality checks are failing or warning?
- What action should an operator take first?