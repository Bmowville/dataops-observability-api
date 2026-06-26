import sys
from os import chdir
from pathlib import Path

from alembic.config import Config

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_URL = "http://127.0.0.1:8000/dashboard"
API_DOCS_URL = "http://127.0.0.1:8000/docs"
OPERATIONS_OVERVIEW_URL = (
    "http://127.0.0.1:8000/api/v1/metrics/operations-overview?stale_after_minutes=60"
)
ALERT_DELIVERIES_URL = "http://127.0.0.1:8000/api/v1/alerts/deliveries?limit=5"


def build_demo_report(summary_json: str) -> str:
    return "\n".join(
        [
            "Demo database ready.",
            "",
            "Seed summary:",
            summary_json,
            "",
            "Start the API:",
            "uvicorn app.main:app --reload",
            "",
            "Open:",
            f"- Dashboard: {DASHBOARD_URL}",
            f"- API docs: {API_DOCS_URL}",
            f"- Operations overview: {OPERATIONS_OVERVIEW_URL}",
            f"- Alert delivery history: {ALERT_DELIVERIES_URL}",
        ]
    )


def main() -> None:
    chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    from app.db.session import SessionLocal
    from app.services.sample_data import seed_sample_data

    alembic_config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    with SessionLocal() as session:
        summary = seed_sample_data(session)

    print(build_demo_report(summary.model_dump_json(indent=2)))


if __name__ == "__main__":
    main()