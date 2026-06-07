"""Example Airflow DAG that reports status to the DataOps Observability API.

Copy this into an Airflow DAGs folder and set DATAOPS_API_URL in the Airflow
environment. This file is an integration example and is not required to run the
FastAPI service.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests
from airflow.decorators import dag, task

DATAOPS_API_URL = os.getenv("DATAOPS_API_URL", "http://dataops-api:8000").rstrip("/")


def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{DATAOPS_API_URL}{path}", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def patch_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.patch(f"{DATAOPS_API_URL}{path}", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


@dag(
    dag_id="orders_daily_load_with_dataops_reporting",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
)
def orders_daily_load() -> None:
    @task
    def start_run() -> int:
        run = post_json(
            "/api/v1/pipeline-runs",
            {
                "name": "orders_daily_load",
                "source_system": "airflow",
                "status": "running",
                "records_processed": 0,
            },
        )
        return int(run["id"])

    @task
    def load_orders() -> int:
        return 1284

    @task
    def report_quality(run_id: int, records_processed: int) -> None:
        post_json(
            f"/api/v1/pipeline-runs/{run_id}/quality-checks",
            {
                "check_name": "row_count_minimum",
                "status": "passed" if records_processed >= 1000 else "failed",
                "severity": "high",
                "expected_value": "1000+",
                "observed_value": str(records_processed),
            },
        )

    @task
    def finish_run(run_id: int, records_processed: int) -> None:
        patch_json(
            f"/api/v1/pipeline-runs/{run_id}",
            {
                "status": "succeeded",
                "records_processed": records_processed,
            },
        )

    run_id = start_run()
    records = load_orders()
    report_quality(run_id, records)
    finish_run(run_id, records)


orders_daily_load()