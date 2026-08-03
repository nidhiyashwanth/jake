"""HTTP contract for form-edited workflow definitions and read-only graphs."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ModelConfig, Prompt, PromptVersion, Workflow, WorkflowEvaluationResult, WorkflowVersion
from app.schemas import (
    ModelConfigCreate,
    PromptCreate,
    PromptVersionCreate,
    WorkflowCreate,
    WorkflowEvaluationCreate,
    WorkflowUpdate,
    WorkflowVersionCreate,
    WorkflowVersionPatch,
)
from app.services.audit import append_audit_log, append_data_access_log
from app.services.authorization import authorize
from app.services.tenancy import current_context, get_scoped_db
from app.services.workflow import (
    create_model_config,
    create_prompt,
    create_prompt_version,
    create_workflow,
    create_workflow_version,
    evaluation_gate_payload,
    evaluation_payload,
    get_workflow_or_404,
    get_workflow_version_or_404,
    graph_payload,
    model_config_payload,
    prompt_payload,
    publish_version,
    record_evaluation,
    update_workflow_version,
    validate_version,
    version_payload,
    workflow_payload,
)


router = APIRouter(prefix="/api")
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


def _workflow_version_or_404(db: Session, workflow_id: str, version_number: int, workspace_id: str) -> tuple[Workflow, WorkflowVersion]:
    workflow = get_workflow_or_404(db, workflow_id, workspace_id)
    version = get_workflow_version_or_404(db, workflow.id, version_number, workspace_id)
    return workflow, version


def _prompt_or_404(db: Session, prompt_id: str, workspace_id: str) -> Prompt:
    prompt = db.scalar(select(Prompt).where(Prompt.id == prompt_id, Prompt.workspace_id == workspace_id))
    if prompt is None:
        raise DomainError("PROMPT_NOT_FOUND", f"Prompt {prompt_id} was not found", 404)
    return prompt


@router.post("/workflows", status_code=201)
def create_workflow_route(payload: WorkflowCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.create", target_type="workflow", target_id=payload.name)
    try:
        workflow, version, validation = create_workflow(
            db,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            payload=payload,
        )
        append_audit_log(
            db,
            action="workflow.created",
            target_type="workflow",
            target_id=workflow.id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            after={"name": workflow.name, "version_id": version.id, "definition_hash": validation.definition_hash},
        )
        db.commit()
        db.refresh(workflow)
        db.refresh(version)
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("WORKFLOW_ALREADY_EXISTS", "A workflow with this name already exists", 409) from exc
    return {"workflow": workflow_payload(db, workflow), "version": version_payload(db, version), "validation": validation.as_dict()}


@router.get("/workflows")
def list_workflows(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.read")
    workflows = db.scalars(
        select(Workflow)
        .where(Workflow.workspace_id == context.workspace_id)
        .order_by(Workflow.updated_at.desc(), Workflow.name.asc())
    ).all()
    for workflow in workflows:
        append_data_access_log(
            db,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            artifact_id=workflow.id,
            resource_type="workflow",
            purpose="workflow_list",
        )
    db.commit()
    return {"items": [workflow_payload(db, workflow) for workflow in workflows]}


@router.get("/workflows/{workflow_id}")
def get_workflow_route(workflow_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.read", target_type="workflow", target_id=workflow_id)
    workflow = get_workflow_or_404(db, workflow_id, context.workspace_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=workflow.id,
        resource_type="workflow",
        purpose="workflow_detail",
    )
    db.commit()
    return workflow_payload(db, workflow)


@router.patch("/workflows/{workflow_id}")
def update_workflow_route(workflow_id: str, payload: WorkflowUpdate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.update", target_type="workflow", target_id=workflow_id)
    workflow = get_workflow_or_404(db, workflow_id, context.workspace_id)
    before = {"name": workflow.name, "description": workflow.description}
    if "name" in payload.model_fields_set:
        workflow.name = payload.name or workflow.name
    if "description" in payload.model_fields_set:
        workflow.description = payload.description
    append_audit_log(
        db,
        action="workflow.updated",
        target_type="workflow",
        target_id=workflow.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        before=before,
        after={"name": workflow.name, "description": workflow.description},
    )
    try:
        db.commit()
        db.refresh(workflow)
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("WORKFLOW_ALREADY_EXISTS", "A workflow with this name already exists", 409) from exc
    return workflow_payload(db, workflow)


@router.get("/workflows/{workflow_id}/versions")
def list_workflow_versions(workflow_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.version.read", target_type="workflow", target_id=workflow_id)
    workflow = get_workflow_or_404(db, workflow_id, context.workspace_id)
    versions = db.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.workspace_id == context.workspace_id)
        .order_by(desc(WorkflowVersion.version))
    ).all()
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=workflow.id,
        resource_type="workflow_versions",
        purpose="workflow_version_list",
    )
    db.commit()
    return {"items": [version_payload(db, version, include_graph=False) for version in versions]}


@router.post("/workflows/{workflow_id}/versions", status_code=201)
def create_workflow_version_route(workflow_id: str, payload: WorkflowVersionCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.version.create", target_type="workflow", target_id=workflow_id)
    workflow = get_workflow_or_404(db, workflow_id, context.workspace_id)
    try:
        version, validation = create_workflow_version(
            db,
            workflow=workflow,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            payload=payload,
        )
        append_audit_log(
            db,
            action="workflow.version.created",
            target_type="workflow_version",
            target_id=version.id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            after={"workflow_id": workflow.id, "version": version.version, "definition_hash": validation.definition_hash},
        )
        db.commit()
        db.refresh(version)
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("WORKFLOW_VERSION_CONFLICT", "The workflow version could not be created concurrently", 409) from exc
    return {"workflow": workflow_payload(db, workflow), "version": version_payload(db, version), "validation": validation.as_dict()}


@router.get("/workflows/{workflow_id}/versions/{version_number}")
def get_workflow_version_route(workflow_id: str, version_number: int, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.version.read", target_type="workflow_version", target_id=f"{workflow_id}:{version_number}")
    _, version = _workflow_version_or_404(db, workflow_id, version_number, context.workspace_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=version.id,
        resource_type="workflow_version",
        purpose="workflow_version_detail",
    )
    db.commit()
    return version_payload(db, version)


@router.patch("/workflows/{workflow_id}/versions/{version_number}")
def update_workflow_version_route(
    workflow_id: str,
    version_number: int,
    payload: WorkflowVersionPatch,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.version.update", target_type="workflow_version", target_id=f"{workflow_id}:{version_number}")
    workflow, version = _workflow_version_or_404(db, workflow_id, version_number, context.workspace_id)
    previous_hash = version.definition_hash
    try:
        validation = update_workflow_version(
            db,
            version=version,
            workflow=workflow,
            workspace_id=context.workspace_id,
            payload=payload,
        )
        append_audit_log(
            db,
            action="workflow.version.updated",
            target_type="workflow_version",
            target_id=version.id,
            workspace_id=context.workspace_id,
            actor_id=context.user_id,
            before={"definition_hash": previous_hash},
            after={"definition_hash": validation.definition_hash, "validation": validation.as_dict()},
        )
        db.commit()
        db.refresh(version)
    except IntegrityError as exc:
        db.rollback()
        raise DomainError("WORKFLOW_VERSION_CONFLICT", "The workflow draft could not be saved", 409) from exc
    return {"version": version_payload(db, version), "validation": validation.as_dict()}


@router.post("/workflows/{workflow_id}/versions/{version_number}/validate")
def validate_workflow_version_route(workflow_id: str, version_number: int, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.validate", target_type="workflow_version", target_id=f"{workflow_id}:{version_number}")
    workflow, version = _workflow_version_or_404(db, workflow_id, version_number, context.workspace_id)
    validation = validate_version(db, version=version, workflow=workflow)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=version.id,
        resource_type="workflow_version",
        purpose="workflow_validation",
    )
    db.commit()
    return {
        **validation.as_dict(),
        "evaluation_gate": evaluation_gate_payload(db, version),
        "publishable": validation.valid and evaluation_gate_payload(db, version)["passed"],
    }


@router.get("/workflows/{workflow_id}/versions/{version_number}/graph")
def get_workflow_graph_route(workflow_id: str, version_number: int, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.version.read", target_type="workflow_version", target_id=f"{workflow_id}:{version_number}")
    _, version = _workflow_version_or_404(db, workflow_id, version_number, context.workspace_id)
    append_data_access_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        artifact_id=version.id,
        resource_type="workflow_graph",
        purpose="workflow_graph_read",
    )
    db.commit()
    return graph_payload(db, version)


@router.get("/workflows/{workflow_id}/versions/{version_number}/evaluations")
def list_workflow_evaluations(workflow_id: str, version_number: int, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.read", target_type="workflow_version", target_id=f"{workflow_id}:{version_number}")
    _, version = _workflow_version_or_404(db, workflow_id, version_number, context.workspace_id)
    results = db.scalars(
        select(WorkflowEvaluationResult)
        .where(
            WorkflowEvaluationResult.workflow_version_id == version.id,
            WorkflowEvaluationResult.workspace_id == context.workspace_id,
        )
        .order_by(WorkflowEvaluationResult.evaluated_at.desc())
    ).all()
    db.commit()
    return {"items": [evaluation_payload(result) for result in results], "gate": evaluation_gate_payload(db, version)}


@router.post("/workflows/{workflow_id}/versions/{version_number}/evaluations", status_code=201)
def record_workflow_evaluation_route(
    workflow_id: str,
    version_number: int,
    payload: WorkflowEvaluationCreate,
    db: ScopedDb,
) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.evaluation.write", target_type="workflow_version", target_id=f"{workflow_id}:{version_number}")
    workflow, version = _workflow_version_or_404(db, workflow_id, version_number, context.workspace_id)
    result = record_evaluation(db, version=version, workflow=workflow, actor_id=context.user_id, payload=payload)
    db.commit()
    db.refresh(result)
    return {"evaluation": evaluation_payload(result), "gate": evaluation_gate_payload(db, version)}


@router.post("/workflows/{workflow_id}/versions/{version_number}/publish")
def publish_workflow_version_route(workflow_id: str, version_number: int, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "workflow.publish", target_type="workflow_version", target_id=f"{workflow_id}:{version_number}")
    workflow, version = _workflow_version_or_404(db, workflow_id, version_number, context.workspace_id)
    evaluation = publish_version(db, version=version, workflow=workflow, actor_id=context.user_id)
    db.commit()
    db.refresh(version)
    db.refresh(workflow)
    return {
        "workflow": workflow_payload(db, workflow),
        "version": version_payload(db, version),
        "evaluation": evaluation_payload(evaluation),
    }


@router.post("/prompts", status_code=201)
def create_prompt_route(payload: PromptCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "prompt.create", target_type="prompt", target_id=payload.key)
    prompt = create_prompt(db, workspace_id=context.workspace_id, actor_id=context.user_id, payload=payload)
    append_audit_log(
        db,
        action="prompt.created",
        target_type="prompt",
        target_id=prompt.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"key": prompt.key, "version": 1},
    )
    db.commit()
    db.refresh(prompt)
    return prompt_payload(db, prompt)


@router.get("/prompts")
def list_prompts_route(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "prompt.read")
    prompts = db.scalars(select(Prompt).where(Prompt.workspace_id == context.workspace_id).order_by(Prompt.key)).all()
    db.commit()
    return {"items": [prompt_payload(db, prompt) for prompt in prompts]}


@router.post("/prompts/{prompt_id}/versions", status_code=201)
def create_prompt_version_route(prompt_id: str, payload: PromptVersionCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "prompt.version.create", target_type="prompt", target_id=prompt_id)
    prompt = _prompt_or_404(db, prompt_id, context.workspace_id)
    version = create_prompt_version(db, prompt=prompt, actor_id=context.user_id, payload=payload)
    append_audit_log(
        db,
        action="prompt.version.created",
        target_type="prompt_version",
        target_id=version.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"prompt_id": prompt.id, "version": version.version},
    )
    db.commit()
    db.refresh(prompt)
    return prompt_payload(db, prompt)


@router.post("/model-configs", status_code=201)
def create_model_config_route(payload: ModelConfigCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "model_config.create", target_type="model_config", target_id=payload.key)
    config = create_model_config(db, workspace_id=context.workspace_id, actor_id=context.user_id, payload=payload)
    db.flush()
    append_audit_log(
        db,
        action="model_config.created",
        target_type="model_config",
        target_id=config.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"key": config.key, "version": config.version, "provider": config.provider},
    )
    db.commit()
    db.refresh(config)
    return model_config_payload(config)


@router.get("/model-configs")
def list_model_configs_route(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "model_config.read")
    configs = db.scalars(
        select(ModelConfig)
        .where(ModelConfig.workspace_id == context.workspace_id)
        .order_by(ModelConfig.key, ModelConfig.version.desc())
    ).all()
    db.commit()
    return {"items": [model_config_payload(config) for config in configs]}
