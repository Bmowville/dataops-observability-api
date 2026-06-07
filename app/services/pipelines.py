from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import PipelineDefinition
from app.schemas.pipeline import PipelineDefinitionCreate, PipelineDefinitionUpdate


def create_pipeline_definition(
    db: Session,
    payload: PipelineDefinitionCreate,
) -> PipelineDefinition:
    definition = PipelineDefinition(
        name=payload.name,
        owner=payload.owner,
        source_system=payload.source_system,
        expected_cadence_minutes=payload.expected_cadence_minutes,
        stale_after_minutes=payload.stale_after_minutes,
        alert_severity=payload.alert_severity.value,
        runbook_url=payload.runbook_url,
        is_enabled=payload.is_enabled,
    )
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


def list_pipeline_definitions(
    db: Session,
    is_enabled: bool | None = None,
    limit: int = 100,
) -> list[PipelineDefinition]:
    statement = select(PipelineDefinition).order_by(PipelineDefinition.name.asc()).limit(limit)
    if is_enabled is not None:
        statement = statement.where(PipelineDefinition.is_enabled == is_enabled)
    return list(db.scalars(statement).all())


def get_pipeline_definition(db: Session, name: str) -> PipelineDefinition | None:
    statement = select(PipelineDefinition).where(PipelineDefinition.name == name)
    return db.scalar(statement)


def update_pipeline_definition(
    db: Session,
    definition: PipelineDefinition,
    payload: PipelineDefinitionUpdate,
) -> PipelineDefinition:
    update_data = payload.model_dump(exclude_unset=True)
    if "owner" in update_data and payload.owner is not None:
        definition.owner = payload.owner
    if "source_system" in update_data and payload.source_system is not None:
        definition.source_system = payload.source_system
    if "expected_cadence_minutes" in update_data:
        definition.expected_cadence_minutes = payload.expected_cadence_minutes
    if "stale_after_minutes" in update_data and payload.stale_after_minutes is not None:
        definition.stale_after_minutes = payload.stale_after_minutes
    if "alert_severity" in update_data and payload.alert_severity is not None:
        definition.alert_severity = payload.alert_severity.value
    if "runbook_url" in update_data:
        definition.runbook_url = payload.runbook_url
    if "is_enabled" in update_data and payload.is_enabled is not None:
        definition.is_enabled = payload.is_enabled

    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition