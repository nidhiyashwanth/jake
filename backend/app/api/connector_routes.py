"""Thin API routes for workspace connectors, the MCP gateway, and vault metadata."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Connector, ConnectorCall, Credential, CredentialAccessLog, McpServer
from app.schemas import (
    ConnectorCreate,
    ConnectorTestRequest,
    CredentialCreate,
    CredentialRotateRequest,
    McpServerCreate,
    McpToolCallRequest,
    WebhookVerifyRequest,
)
from app.services.audit import append_audit_log
from app.services.authorization import authorize
from app.services.connectors import (
    EnvelopeVault,
    _get_connector,
    _get_credential,
    _get_mcp_server,
    connector_call_payload,
    connector_payload,
    create_connector,
    create_mcp_server,
    credential_payload,
    invoke_mcp_tool,
    mcp_server_payload,
    test_connector,
    verify_webhook_signature,
)
from app.services.tenancy import current_context, get_scoped_db


router = APIRouter(prefix="/api", tags=["connectors"])
ScopedDb = Annotated[Session, Depends(get_scoped_db)]


@router.get("/connectors")
def list_connectors(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "connector.read", target_type="connector_index", target_id=context.workspace_id)
    connectors = db.scalars(select(Connector).where(Connector.workspace_id == context.workspace_id).order_by(Connector.name)).all()
    items = []
    for connector in connectors:
        count = db.scalar(select(func.count(Credential.id)).where(Credential.connector_id == connector.id, Credential.workspace_id == context.workspace_id)) or 0
        items.append(connector_payload(connector, credential_count=int(count)))
    return {"items": items, "count": len(items)}


@router.post("/connectors", status_code=201)
def create_connector_route(payload: ConnectorCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "connector.manage", target_type="connector", target_id=payload.name)
    connector = create_connector(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        name=payload.name,
        kind=payload.kind,
        config=payload.config,
        egress_hosts=payload.egress_hosts,
    )
    append_audit_log(
        db,
        action="connector.created",
        target_type="connector",
        target_id=connector.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"kind": connector.kind, "egress_hosts": connector.egress_hosts_json},
    )
    db.commit()
    return {"connector": connector_payload(connector)}


@router.get("/connectors/{connector_id}")
def get_connector_route(connector_id: str, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "connector.read", target_type="connector", target_id=connector_id)
    connector = _get_connector(db, context.workspace_id, connector_id)
    count = db.scalar(select(func.count(Credential.id)).where(Credential.connector_id == connector.id, Credential.workspace_id == context.workspace_id)) or 0
    return {"connector": connector_payload(connector, credential_count=int(count))}


@router.post("/connectors/{connector_id}/test")
def test_connector_route(connector_id: str, payload: ConnectorTestRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "connector.test", target_type="connector", target_id=connector_id)
    connector = _get_connector(db, context.workspace_id, connector_id)
    result = test_connector(db, connector, actor_id=context.user_id, target=payload.target)
    append_audit_log(
        db,
        action="connector.tested",
        target_type="connector",
        target_id=connector.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"healthy": result["healthy"], "failure_code": result.get("failure", {}).get("code")},
    )
    db.commit()
    return result


@router.post("/connectors/{connector_id}/webhook/verify")
def verify_webhook_route(connector_id: str, payload: WebhookVerifyRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "connector.test", target_type="webhook", target_id=connector_id)
    connector = _get_connector(db, context.workspace_id, connector_id)
    result = verify_webhook_signature(
        db,
        connector,
        actor_id=context.user_id,
        body=payload.body,
        timestamp=payload.timestamp,
        signature=payload.signature,
    )
    append_audit_log(
        db,
        action="webhook.signature_verified",
        target_type="connector",
        target_id=connector.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"verified": result["verified"], "failure_code": result.get("failure_code"), "body_sha256": result["body_sha256"]},
    )
    db.commit()
    return result


@router.post("/connectors/{connector_id}/credentials", status_code=201)
def create_credential_route(connector_id: str, payload: CredentialCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "credential.manage", target_type="connector_credential", target_id=connector_id)
    connector = _get_connector(db, context.workspace_id, connector_id)
    credential = EnvelopeVault(db, workspace_id=context.workspace_id, actor_id=context.user_id).put(
        connector,
        label=payload.label,
        secret=payload.secret.get_secret_value(),
        secret_type=payload.secret_type,
        expires_at=payload.expires_at,
    )
    connector.config_json = {**connector.config_json, "credential_id": credential.id}
    append_audit_log(
        db,
        action="credential.created",
        target_type="credential",
        target_id=credential.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"connector_id": connector.id, "secret_type": credential.secret_type, "ciphertext_only": True},
    )
    db.commit()
    return {"credential": credential_payload(credential)}


@router.post("/connectors/{connector_id}/credentials/{credential_id}/rotate")
def rotate_credential_route(connector_id: str, credential_id: str, payload: CredentialRotateRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "credential.manage", target_type="credential", target_id=credential_id)
    connector = _get_connector(db, context.workspace_id, connector_id)
    credential = _get_credential(db, context.workspace_id, credential_id)
    if credential.connector_id != connector.id:
        raise DomainError("CREDENTIAL_CONNECTOR_MISMATCH", "The credential does not belong to this connector", 404)
    rotated = EnvelopeVault(db, workspace_id=context.workspace_id, actor_id=context.user_id).rotate(
        credential,
        secret=payload.secret.get_secret_value(),
        expires_at=payload.expires_at,
    )
    append_audit_log(
        db,
        action="credential.rotated",
        target_type="credential",
        target_id=rotated.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"connector_id": connector.id, "ciphertext_only": True},
    )
    db.commit()
    return {"credential": credential_payload(rotated)}


@router.get("/credentials/access-log")
def credential_access_log(db: ScopedDb, limit: int = 100) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "credential.access.read", target_type="credential_access_log", target_id=context.workspace_id)
    bounded_limit = max(1, min(limit, 200))
    rows = db.scalars(
        select(CredentialAccessLog)
        .where(CredentialAccessLog.workspace_id == context.workspace_id)
        .order_by(CredentialAccessLog.created_at.desc(), CredentialAccessLog.id.desc())
        .limit(bounded_limit)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "credential_id": row.credential_id,
                "actor_id": row.actor_id,
                "action": row.action,
                "purpose": row.purpose,
                "outcome": row.outcome,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.get("/mcp/servers")
def list_mcp_servers(db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "mcp.read", target_type="mcp_server_index", target_id=context.workspace_id)
    servers = db.scalars(select(McpServer).where(McpServer.workspace_id == context.workspace_id).order_by(McpServer.name)).all()
    return {"items": [mcp_server_payload(server) for server in servers], "count": len(servers)}


@router.post("/mcp/servers", status_code=201)
def create_mcp_server_route(payload: McpServerCreate, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "connector.manage", target_type="mcp_server", target_id=payload.name)
    server = create_mcp_server(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        name=payload.name,
        url=payload.url,
        auth_mode=payload.auth_mode,
        server_version=payload.server_version,
        metadata=payload.metadata,
        allowed_tools=payload.allowed_tools,
        workflow_version_ids=payload.workflow_version_ids,
        egress_hosts=payload.egress_hosts,
    )
    append_audit_log(
        db,
        action="mcp.server_pinned",
        target_type="mcp_server",
        target_id=server.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"metadata_hash": server.metadata_hash, "server_version": server.server_version, "allowed_tools": server.allowed_tools_json},
    )
    db.commit()
    return {"server": mcp_server_payload(server)}


@router.post("/mcp/servers/{server_id}/tools/call")
def call_mcp_tool(server_id: str, payload: McpToolCallRequest, db: ScopedDb) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "mcp.call", target_type="mcp_server", target_id=server_id)
    server = _get_mcp_server(db, context.workspace_id, server_id)
    result = invoke_mcp_tool(db, server, actor_id=context.user_id, request=payload)
    append_audit_log(
        db,
        action="mcp.tool_called",
        target_type="mcp_server",
        target_id=server.id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        after={"tool_name": payload.tool_name, "status": result["call"]["status"], "result_untrusted": True},
    )
    db.commit()
    return result


@router.get("/mcp/calls")
def list_mcp_calls(db: ScopedDb, limit: int = 100) -> dict[str, Any]:
    context = current_context(db)
    authorize(db, context, "mcp.read", target_type="mcp_call_index", target_id=context.workspace_id)
    bounded_limit = max(1, min(limit, 200))
    calls = db.scalars(
        select(ConnectorCall)
        .where(ConnectorCall.workspace_id == context.workspace_id)
        .order_by(ConnectorCall.created_at.desc(), ConnectorCall.id.desc())
        .limit(bounded_limit)
    ).all()
    return {"items": [connector_call_payload(call) for call in calls], "count": len(calls)}
