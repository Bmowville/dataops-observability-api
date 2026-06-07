from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.pipeline import AlertDeliveryRead, AlertDeliveryStatus
from app.services.alert_deliveries import get_latest_alert_delivery, list_alert_deliveries

router = APIRouter(tags=["alerts"])


@router.get("/alerts/deliveries", response_model=list[AlertDeliveryRead])
def read_alert_deliveries(
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[AlertDeliveryStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertDeliveryRead]:
    return [
        AlertDeliveryRead.model_validate(delivery)
        for delivery in list_alert_deliveries(db, status=status_filter, limit=limit)
    ]


@router.get("/alerts/deliveries/latest", response_model=AlertDeliveryRead)
def read_latest_alert_delivery(db: Annotated[Session, Depends(get_db)]) -> AlertDeliveryRead:
    delivery = get_latest_alert_delivery(db)
    if delivery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert delivery not found",
        )
    return AlertDeliveryRead.model_validate(delivery)