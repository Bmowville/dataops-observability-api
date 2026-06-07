# Integration Guide

DataOps Observability API is useful when pipeline runners report a small amount of structured status data into the service. The API does not need to run the pipeline itself. It records what happened, keeps quality-check context next to the run, and powers the dashboard from those records.

## Reporting Flow

1. Create a pipeline run when work starts.
2. Add one or more quality checks while the job runs or after validation finishes.
3. Patch the pipeline run to `succeeded`, `failed`, or `canceled` when work ends.
4. Open `/dashboard` or call `/api/v1/metrics/operations-overview` to see the operating state.

## Common Event Shapes

Create a run:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline-runs \
  -H "Content-Type: application/json" \
  -d '{"name":"orders_daily_load","source_system":"airflow","status":"running","records_processed":0}'
```

Add a quality check:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline-runs/1/quality-checks \
  -H "Content-Type: application/json" \
  -d '{"check_name":"row_count_minimum","status":"passed","severity":"high","expected_value":"1000+","observed_value":"1284"}'
```

Finish the run:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/pipeline-runs/1 \
  -H "Content-Type: application/json" \
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

Copy `examples/integrations/airflow_dag.py` into your Airflow DAGs folder and set `DATAOPS_API_URL` in the Airflow environment. The DAG demonstrates the reporting shape without requiring the API to own scheduling or orchestration.

## GitHub Actions

Copy `examples/integrations/github-actions-report.yml` into `.github/workflows/` in the repository that owns the data job. Replace the placeholder job step with the actual pipeline command and point `DATAOPS_API_URL` at a reachable DataOps Observability API deployment.

For production use, store the API URL and any future credentials as GitHub Actions secrets instead of hard-coding them in the workflow file.

## What This Enables

Once pipelines report this minimal status data, the dashboard and metrics endpoints can answer operational questions without searching logs:

- Which pipelines need attention right now?
- Which runs are stale or still active past the expected window?
- Which quality checks are failing or warning?
- What action should an operator take first?