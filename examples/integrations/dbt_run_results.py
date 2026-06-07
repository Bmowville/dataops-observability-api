"""Report dbt run_results.json into the DataOps Observability API.

Example:

    dbt build
    python examples/integrations/dbt_run_results.py target/run_results.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE_URL = os.getenv("DATAOPS_API_URL", "http://127.0.0.1:8000").rstrip("/")
PASSED_STATUSES = {"success", "pass"}
WARNING_STATUSES = {"warn", "skipped"}


def request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
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


def quality_status(result_status: str) -> str:
    if result_status in PASSED_STATUSES:
        return "passed"
    if result_status in WARNING_STATUSES:
        return "warning"
    return "failed"


def report_dbt_results(results_path: Path) -> dict[str, Any]:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    results = payload.get("results", [])
    failed_count = 0

    run = request_json(
        "POST",
        "/api/v1/pipeline-runs",
        {
            "name": os.getenv("DATAOPS_PIPELINE_NAME", "dbt_build"),
            "source_system": os.getenv("DATAOPS_SOURCE_SYSTEM", "dbt"),
            "status": "running",
            "records_processed": len(results),
        },
    )
    run_id = int(run["id"])

    for result in results:
        node = result.get("node", {})
        result_status = str(result.get("status", "error"))
        check_status = quality_status(result_status)
        if check_status == "failed":
            failed_count += 1

        request_json(
            "POST",
            f"/api/v1/pipeline-runs/{run_id}/quality-checks",
            {
                "check_name": str(node.get("name") or result.get("unique_id") or "dbt_result"),
                "status": check_status,
                "severity": "high" if check_status == "failed" else "medium",
                "expected_value": "dbt status success or pass",
                "observed_value": result_status,
                "details": str(result.get("message") or "dbt node result"),
            },
        )

    final_run = request_json(
        "PATCH",
        f"/api/v1/pipeline-runs/{run_id}",
        {
            "status": "failed" if failed_count else "succeeded",
            "records_processed": len(results),
            "error_message": None if failed_count == 0 else f"{failed_count} dbt results failed.",
        },
    )
    return final_run


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python examples/integrations/dbt_run_results.py target/run_results.json")
        return 2

    try:
        final_run = report_dbt_results(Path(sys.argv[1]))
    except FileNotFoundError:
        print(f"File not found: {sys.argv[1]}", file=sys.stderr)
        return 1
    except HTTPError as error:
        print(error.read().decode("utf-8"), file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as error:
        print(f"Could not reach {API_BASE_URL}: {error}", file=sys.stderr)
        return 1

    print(json.dumps(final_run, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())