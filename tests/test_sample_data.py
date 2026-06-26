from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import AlertDelivery
from app.services.sample_data import SAMPLE_ALERT_RECEIVERS, seed_sample_data


def test_seed_sample_data_creates_idempotent_alert_delivery_history(
    db_session: Session,
) -> None:
    first_summary = seed_sample_data(db_session)
    second_summary = seed_sample_data(db_session)

    deliveries = list(
        db_session.scalars(
            select(AlertDelivery)
            .where(AlertDelivery.receiver.in_(SAMPLE_ALERT_RECEIVERS))
            .order_by(AlertDelivery.created_at.desc(), AlertDelivery.id.desc())
        )
    )

    assert first_summary.alert_deliveries_created == 2
    assert second_summary.alert_deliveries_created == 2
    assert len(deliveries) == 2
    assert [delivery.event_type for delivery in deliveries] == [
        "quality_check_warning",
        "pipeline_run_failed",
    ]
    assert {delivery.status for delivery in deliveries} == {"failed", "succeeded"}