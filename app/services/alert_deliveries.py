from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import AlertDelivery
from app.schemas.pipeline import AlertDeliveryStatus


def create_alert_delivery(
    db: Session,
    *,
    event_type: str,
    pipeline_run_id: int | None,
    quality_check_id: int | None,
    receiver: str,
    status: AlertDeliveryStatus,
    http_status_code: int | None = None,
    error_message: str | None = None,
) -> AlertDelivery:
    delivery = AlertDelivery(
        event_type=event_type,
        pipeline_run_id=pipeline_run_id,
        quality_check_id=quality_check_id,
        receiver=receiver,
        status=status.value,
        http_status_code=http_status_code,
        error_message=error_message,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def list_alert_deliveries(
    db: Session,
    status: AlertDeliveryStatus | None = None,
    limit: int = 100,
) -> list[AlertDelivery]:
    statement = (
        select(AlertDelivery)
        .order_by(AlertDelivery.created_at.desc(), AlertDelivery.id.desc())
        .limit(limit)
    )
    if status is not None:
        statement = statement.where(AlertDelivery.status == status.value)
    return list(db.scalars(statement).all())


def get_latest_alert_delivery(db: Session) -> AlertDelivery | None:
    statement = (
        select(AlertDelivery)
        .order_by(AlertDelivery.created_at.desc(), AlertDelivery.id.desc())
        .limit(1)
    )
    return db.scalar(statement)
