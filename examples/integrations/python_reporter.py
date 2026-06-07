"""Report a simple Python data job into the DataOps Observability API.

Run the API locally first:

    alembic upgrade head
    uvicorn app.main:app --reload

Then run this example:

    python examples/integrations/python_reporter.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE_URL = os.getenv("DATAOPS_API_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("DATAOPS_API_KEY", "")


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-DataOps-API-Key"] = API_KEY
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        url=f"{API_BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def create_run(name: str, source_system: str) -> dict[str, Any]:
    return request_json(
        "POST",
        "/api/v1/pipeline-runs",
        {
            "name": name,
            "source_system": source_system,
            "status": "running",
            "records_processed": 0,
        },
    )


def add_quality_check(run_id: int, records_processed: int) -> dict[str, Any]:
    status = "passed" if records_processed >= 1 else "failed"
    return request_json(
        "POST",
        f"/api/v1/pipeline-runs/{run_id}/quality-checks",
        {
            "check_name": "minimum_records_processed",
            "status": status,
            "severity": "high",
            "expected_value": "at least 1 record",
            "observed_value": str(records_processed),
            "details": "Basic completeness check from the Python reporter example.",
        },
    )


def finish_run(run_id: int, records_processed: int, succeeded: bool) -> dict[str, Any]:
    return request_json(
        "PATCH",
        f"/api/v1/pipeline-runs/{run_id}",
        {
            "status": "succeeded" if succeeded else "failed",
            "records_processed": records_processed,
            "error_message": None if succeeded else "Example job reported a failed check.",
        },
    )


def main() -> int:
    pipeline_name = os.getenv("DATAOPS_PIPELINE_NAME", "example_python_job")
    source_system = os.getenv("DATAOPS_SOURCE_SYSTEM", "python_script")
    records_processed = int(os.getenv("DATAOPS_RECORDS_PROCESSED", "1284"))

    try:
        run = create_run(pipeline_name, source_system)
        check = add_quality_check(int(run["id"]), records_processed)
        final_run = finish_run(
            int(run["id"]),
            records_processed=records_processed,
            succeeded=check["status"] != "failed",
        )
    except HTTPError as error:
        print(error.read().decode("utf-8"), file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as error:
        print(f"Could not reach {API_BASE_URL}: {error}", file=sys.stderr)
        return 1

    print(json.dumps({"run": final_run, "quality_check": check}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())