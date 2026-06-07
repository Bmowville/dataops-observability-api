from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_ingestion_api_key
from app.db.session import get_db
from app.models.pipeline import PipelineDefinition
from app.schemas.pipeline import (
    PipelineDefinitionCreate,
    PipelineDefinitionRead,
    PipelineDefinitionUpdate,
)
from app.services.pipelines import (
    create_pipeline_definition,
    get_pipeline_definition,
    list_pipeline_definitions,
    update_pipeline_definition,
)

router = APIRouter(tags=["pipelines"])


def _get_pipeline_or_404(db: Session, name: str) -> PipelineDefinition:
    definition = get_pipeline_definition(db, name)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return definition


@router.post(
    "/pipelines",
    response_model=PipelineDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_ingestion_api_key)],
)
def create_pipeline(
    payload: PipelineDefinitionCreate,
    db: Annotated[Session, Depends(get_db)],
) -> PipelineDefinitionRead:
    try:
        definition = create_pipeline_definition(db, payload)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline already exists",
        ) from error
    return PipelineDefinitionRead.model_validate(definition)


@router.get("/pipelines", response_model=list[PipelineDefinitionRead])
def list_pipelines(
    db: Annotated[Session, Depends(get_db)],
    enabled: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PipelineDefinitionRead]:
    return [
        PipelineDefinitionRead.model_validate(definition)
        for definition in list_pipeline_definitions(db, is_enabled=enabled, limit=limit)
    ]


@router.get("/pipelines/{name}", response_model=PipelineDefinitionRead)
def read_pipeline(name: str, db: Annotated[Session, Depends(get_db)]) -> PipelineDefinitionRead:
    return PipelineDefinitionRead.model_validate(_get_pipeline_or_404(db, name))


@router.patch(
    "/pipelines/{name}",
    response_model=PipelineDefinitionRead,
    dependencies=[Depends(require_ingestion_api_key)],
)
def patch_pipeline(
    name: str,
    payload: PipelineDefinitionUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> PipelineDefinitionRead:
    definition = _get_pipeline_or_404(db, name)
    updated = update_pipeline_definition(db, definition, payload)
    return PipelineDefinitionRead.model_validate(updated)