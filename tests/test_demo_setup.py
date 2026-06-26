from app.schemas.pipeline import SeedSampleDataSummary
from scripts.demo_setup import ALERT_DELIVERIES_URL, DASHBOARD_URL, build_demo_report


def test_build_demo_report_includes_demo_entry_points() -> None:
    summary = SeedSampleDataSummary(
        pipelines_registered=2,
        pipeline_runs_created=3,
        quality_checks_created=4,
        alert_deliveries_created=2,
        source_system="sample_seed",
    )

    report = build_demo_report(summary.model_dump_json(indent=2))

    assert "Demo database ready." in report
    assert "uvicorn app.main:app --reload" in report
    assert DASHBOARD_URL in report
    assert ALERT_DELIVERIES_URL in report
    assert '"alert_deliveries_created": 2' in report