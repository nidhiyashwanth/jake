"""Workspace-scoped connector, MCP, and envelope-vault boundaries."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import DomainError
from app.models import (
    Connector,
    ConnectorCall,
    Credential,
    CredentialAccessLog,
    McpServer,
    WorkspaceKeyEnvelope,
    new_id,
    utc_now,
)


CONNECTOR_KINDS = frozenset({"email", "object_storage", "notify", "rest", "webhook", "sftp", "database", "csv_excel", "rpa"})
SUPPORTED_SANDBOX_KINDS = frozenset({"email", "object_storage", "notify", "rest", "webhook", "sftp", "database", "csv_excel"})
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "private_key",
        "client_secret",
        "authorization",
    }
)
SENSITIVE_STRING = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")


class ConnectorAdapter(Protocol):
    kind: str

    def test(self, *, target: str, config: dict[str, Any]) -> dict[str, Any]:
        """Run a bounded provider health check without returning credentials."""


class SandboxConnectorAdapter:
    """Deterministic provider used by dev/staging verification; no external egress."""

    def __init__(self, kind: str):
        self.kind = kind

    def test(self, *, target: str, config: dict[str, Any]) -> dict[str, Any]:
        read_only = self.kind in {"email", "object_storage", "sftp", "database", "csv_excel"}
        return {
            "provider": "sandbox",
            "kind": self.kind,
            "target": target,
            "read_only": read_only,
            "untrusted_output": True,
            "capabilities": {
                "ingest": self.kind in {"email", "object_storage", "sftp", "database", "csv_excel"},
                "notify": self.kind in {"notify", "webhook", "rest"},
                "write": self.kind in {"notify", "webhook", "rest", "object_storage", "csv_excel"},
            },
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _metadata_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _key_is_sensitive(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in SENSITIVE_KEYS or any(
        fragment in normalized for fragment in ("password", "secret", "access_token", "refresh_token", "api_key", "private_key")
    )


def reject_secret_like_config(value: Any, *, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if _key_is_sensitive(str(key)):
                raise DomainError("CONNECTOR_SECRET_IN_CONFIG", f"Raw secret-like field '{path}.{key}' is not accepted; use the vault", 422)
            reject_secret_like_config(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            reject_secret_like_config(nested, path=f"{path}[{index}]")


def redact_untrusted(value: Any, *, _key: str | None = None) -> Any:
    """Redact secrets and bound untrusted tool data before persistence or response."""

    if _key is not None and _key_is_sensitive(_key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(key): redact_untrusted(nested, _key=str(key)) for key, nested in value.items()}
    if isinstance(value, list):
        return [redact_untrusted(nested) for nested in value[:100]]
    if isinstance(value, str):
        bounded = value[:4000]
        return SENSITIVE_STRING.sub("[REDACTED]", bounded)
    return value


def _normalize_hosts(hosts: list[str]) -> list[str]:
    normalized = []
    for host in hosts:
        item = host.strip().casefold()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _url_host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https", "sandbox"} or not parsed.hostname:
        raise DomainError("CONNECTOR_URL_INVALID", "Connector targets must use an http(s) or sandbox URL with a hostname", 422)
    return parsed.hostname.casefold()


def _validate_egress(url: str, egress_hosts: list[str]) -> str:
    host = _url_host(url)
    global_allowlist = set(get_settings().connector_egress_allowlist_list)
    if host not in global_allowlist:
        raise DomainError("EGRESS_NOT_ALLOWED", f"Outbound host '{host}' is not in the deployment egress allow-list", 422)
    if egress_hosts and host not in set(egress_hosts):
        raise DomainError("EGRESS_NOT_ALLOWED", f"Outbound host '{host}' is not in this connector's egress allow-list", 422)
    return host


def _get_connector(db: Session, workspace_id: str, connector_id: str) -> Connector:
    connector = db.scalar(select(Connector).where(Connector.id == connector_id, Connector.workspace_id == workspace_id))
    if connector is None:
        raise DomainError("CONNECTOR_NOT_FOUND", f"Connector {connector_id} was not found", 404)
    return connector


def _get_credential(db: Session, workspace_id: str, credential_id: str) -> Credential:
    credential = db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == workspace_id))
    if credential is None:
        raise DomainError("CREDENTIAL_NOT_FOUND", f"Credential {credential_id} was not found", 404)
    return credential


def _get_mcp_server(db: Session, workspace_id: str, server_id: str) -> McpServer:
    server = db.scalar(select(McpServer).where(McpServer.id == server_id, McpServer.workspace_id == workspace_id))
    if server is None:
        raise DomainError("MCP_SERVER_NOT_FOUND", f"MCP server {server_id} was not found", 404)
    return server


class EnvelopeVault:
    """AES-GCM envelope vault with a deployment KEK boundary and per-workspace DEKs."""

    def __init__(self, db: Session, *, workspace_id: str, actor_id: str | None):
        self.db = db
        self.workspace_id = workspace_id
        self.actor_id = actor_id
        self.settings = get_settings()

    def _kek(self) -> bytes:
        if self.settings.vault_kek_base64:
            return base64.b64decode(self.settings.vault_kek_base64, validate=True)
        # Development-only KMS seam. Production settings reject the absence of a
        # deployment-managed KEK before the application starts.
        return hashlib.sha256(("local-kms-boundary-v1:" + self.settings.database_url).encode("utf-8")).digest()

    def _key_aad(self, dek_id: str) -> bytes:
        return f"workspace:{self.workspace_id}:dek:{dek_id}:version:{self.settings.vault_key_version}".encode("utf-8")

    def _credential_aad(self, credential_id: str) -> bytes:
        return f"workspace:{self.workspace_id}:credential:{credential_id}".encode("utf-8")

    def _workspace_dek(self) -> tuple[WorkspaceKeyEnvelope, bytes]:
        envelope = self.db.scalar(select(WorkspaceKeyEnvelope).where(WorkspaceKeyEnvelope.workspace_id == self.workspace_id))
        if envelope is None:
            dek_id = f"dek_{secrets.token_urlsafe(16)}"
            dek = secrets.token_bytes(32)
            nonce = secrets.token_bytes(12)
            encrypted = AESGCM(self._kek()).encrypt(nonce, dek, self._key_aad(dek_id))
            envelope = WorkspaceKeyEnvelope(
                id=new_id(),
                workspace_id=self.workspace_id,
                dek_id=dek_id,
                encrypted_dek=encrypted,
                nonce=nonce,
                key_version=self.settings.vault_key_version,
                created_at=utc_now(),
                rotated_at=utc_now(),
            )
            self.db.add(envelope)
            self.db.flush()
            return envelope, dek
        try:
            dek = AESGCM(self._kek()).decrypt(envelope.nonce, envelope.encrypted_dek, self._key_aad(envelope.dek_id))
        except Exception as exc:
            raise DomainError("VAULT_KEY_UNWRAP_FAILED", "The workspace key could not be unwrapped by the configured KMS boundary", 503) from exc
        return envelope, dek

    def _record_access(self, credential: Credential, *, action: str, purpose: str, outcome: str) -> None:
        self.db.add(
            CredentialAccessLog(
                id=new_id(),
                workspace_id=self.workspace_id,
                credential_id=credential.id,
                actor_id=self.actor_id,
                action=action,
                purpose=purpose,
                outcome=outcome,
                created_at=utc_now(),
            )
        )

    def put(self, connector: Connector, *, label: str, secret: str, secret_type: str, expires_at: datetime | None) -> Credential:
        if not secret:
            raise DomainError("CREDENTIAL_SECRET_REQUIRED", "A credential secret is required", 422)
        envelope, dek = self._workspace_dek()
        credential_id = new_id()
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(dek).encrypt(nonce, secret.encode("utf-8"), self._credential_aad(credential_id))
        credential = Credential(
            id=credential_id,
            workspace_id=self.workspace_id,
            connector_id=connector.id,
            label=" ".join(label.split()),
            secret_type=secret_type,
            ciphertext=ciphertext,
            nonce=nonce,
            dek_id=envelope.dek_id,
            key_version=envelope.key_version,
            expires_at=expires_at,
            rotated_at=utc_now(),
            active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.db.add(credential)
        self.db.flush()
        self._record_access(credential, action="credential.created", purpose="credential_write", outcome="stored_ciphertext")
        return credential

    def rotate(self, credential: Credential, *, secret: str, expires_at: datetime | None) -> Credential:
        if not secret:
            raise DomainError("CREDENTIAL_SECRET_REQUIRED", "A credential secret is required", 422)
        envelope, dek = self._workspace_dek()
        nonce = secrets.token_bytes(12)
        credential.ciphertext = AESGCM(dek).encrypt(nonce, secret.encode("utf-8"), self._credential_aad(credential.id))
        credential.nonce = nonce
        credential.dek_id = envelope.dek_id
        credential.key_version = envelope.key_version
        credential.expires_at = expires_at
        credential.rotated_at = utc_now()
        credential.updated_at = credential.rotated_at
        credential.active = True
        self._record_access(credential, action="credential.rotated", purpose="credential_rotation", outcome="stored_ciphertext")
        return credential

    def read(self, credential: Credential, *, purpose: str) -> str:
        if not credential.active:
            self._record_access(credential, action="credential.read", purpose=purpose, outcome="inactive")
            raise DomainError("CREDENTIAL_INACTIVE", "The credential is inactive", 409)
        if credential.expires_at and credential.expires_at <= datetime.now(timezone.utc):
            self._record_access(credential, action="credential.read", purpose=purpose, outcome="expired")
            raise DomainError("CREDENTIAL_EXPIRED", "The credential has expired", 409)
        envelope, dek = self._workspace_dek()
        if envelope.dek_id != credential.dek_id:
            self._record_access(credential, action="credential.read", purpose=purpose, outcome="key_mismatch")
            raise DomainError("VAULT_KEY_MISMATCH", "The credential is not encrypted with the active workspace key", 503)
        try:
            value = AESGCM(dek).decrypt(credential.nonce, credential.ciphertext, self._credential_aad(credential.id)).decode("utf-8")
        except Exception as exc:
            self._record_access(credential, action="credential.read", purpose=purpose, outcome="decrypt_failed")
            raise DomainError("VAULT_DECRYPT_FAILED", "The credential could not be decrypted", 503) from exc
        self._record_access(credential, action="credential.read", purpose=purpose, outcome="decrypted_in_memory")
        return value


def connector_payload(connector: Connector, *, credential_count: int = 0) -> dict[str, Any]:
    return {
        "id": connector.id,
        "name": connector.name,
        "kind": connector.kind,
        "status": connector.status,
        "config": redact_untrusted(connector.config_json),
        "egress_hosts": connector.egress_hosts_json,
        "credential_count": credential_count,
        "failure_code": connector.failure_code,
        "failure_message": connector.failure_message,
        "last_checked_at": connector.last_checked_at.isoformat() if connector.last_checked_at else None,
        "created_at": connector.created_at.isoformat(),
        "updated_at": connector.updated_at.isoformat(),
    }


def credential_payload(credential: Credential) -> dict[str, Any]:
    return {
        "id": credential.id,
        "connector_id": credential.connector_id,
        "label": credential.label,
        "secret_type": credential.secret_type,
        "ciphertext_present": bool(credential.ciphertext),
        "plaintext_exposed": False,
        "dek_id": credential.dek_id,
        "key_version": credential.key_version,
        "expires_at": credential.expires_at.isoformat() if credential.expires_at else None,
        "rotated_at": credential.rotated_at.isoformat(),
        "active": credential.active,
        "created_at": credential.created_at.isoformat(),
    }


def mcp_server_payload(server: McpServer) -> dict[str, Any]:
    return {
        "id": server.id,
        "name": server.name,
        "url": server.url,
        "auth_mode": server.auth_mode,
        "server_version": server.server_version,
        "metadata_hash": server.metadata_hash,
        "allowed_tools": server.allowed_tools_json,
        "workflow_version_ids": server.workflow_version_ids_json,
        "egress_hosts": server.egress_hosts_json,
        "status": server.status,
        "created_at": server.created_at.isoformat(),
        "updated_at": server.updated_at.isoformat(),
    }


def connector_call_payload(call: ConnectorCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "connector_id": call.connector_id,
        "mcp_server_id": call.mcp_server_id,
        "workflow_version_id": call.workflow_version_id,
        "call_type": call.call_type,
        "tool_name": call.tool_name,
        "arguments": redact_untrusted(call.arguments_json),
        "result": redact_untrusted(call.result_json) if call.result_json is not None else None,
        "result_untrusted": call.result_untrusted,
        "status": call.status,
        "failure_code": call.failure_code,
        "approval_required": call.approval_required,
        "egress_host": call.egress_host,
        "idempotency_key": call.idempotency_key,
        "correlation_id": call.correlation_id,
        "latency_ms": call.latency_ms,
        "created_at": call.created_at.isoformat(),
    }


def create_connector(db: Session, *, workspace_id: str, actor_id: str, name: str, kind: str, config: dict[str, Any], egress_hosts: list[str]) -> Connector:
    if kind not in CONNECTOR_KINDS:
        raise DomainError("CONNECTOR_KIND_UNSUPPORTED", f"Connector kind '{kind}' is not supported", 422)
    reject_secret_like_config(config)
    normalized_hosts = _normalize_hosts(egress_hosts)
    unknown_hosts = sorted(set(normalized_hosts) - set(get_settings().connector_egress_allowlist_list))
    if unknown_hosts:
        raise DomainError("EGRESS_NOT_ALLOWED", f"Connector egress host is not in the deployment allow-list: {unknown_hosts[0]}", 422)
    connector = Connector(
        id=new_id(),
        workspace_id=workspace_id,
        name=" ".join(name.split()),
        kind=kind,
        status="unconfigured",
        config_json=config,
        egress_hosts_json=normalized_hosts,
        created_by=actor_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(connector)
    db.flush()
    return connector


def test_connector(db: Session, connector: Connector, *, actor_id: str, target: str | None = None) -> dict[str, Any]:
    checked_at = utc_now()
    try:
        if connector.kind == "rpa":
            if connector.config_json.get("execution_isolation") != "sandbox":
                raise DomainError("RPA_ISOLATION_REQUIRED", "RPA is disabled unless an explicit isolated sandbox runner is configured", 422)
            result = {"provider": "sandbox", "kind": "rpa", "isolated": True, "untrusted_output": True}
        elif connector.kind not in SUPPORTED_SANDBOX_KINDS:
            raise DomainError("CONNECTOR_PROVIDER_NOT_CONFIGURED", "This connector kind has no configured provider adapter", 503)
        else:
            selected_target = target or str(connector.config_json.get("endpoint") or f"sandbox://{connector.kind}.local")
            host = _validate_egress(selected_target, connector.egress_hosts_json)
            credential_id = connector.config_json.get("credential_id")
            if credential_id:
                credential = _get_credential(db, connector.workspace_id, str(credential_id))
                EnvelopeVault(db, workspace_id=connector.workspace_id, actor_id=actor_id).read(credential, purpose="connector_test")
            result = SandboxConnectorAdapter(connector.kind).test(target=selected_target, config=connector.config_json)
            result["egress_host"] = host
        connector.status = "healthy"
        connector.failure_code = None
        connector.failure_message = None
        connector.last_checked_at = checked_at
        db.flush()
        return {"healthy": True, "connector": connector_payload(connector), "result": redact_untrusted(result)}
    except DomainError as exc:
        connector.status = "unhealthy"
        connector.failure_code = exc.code
        connector.failure_message = exc.message
        connector.last_checked_at = checked_at
        db.flush()
        return {"healthy": False, "connector": connector_payload(connector), "failure": {"code": exc.code, "message": exc.message}}


def verify_webhook_signature(db: Session, connector: Connector, *, actor_id: str, body: str, timestamp: int, signature: str) -> dict[str, Any]:
    """Verify a timestamped HMAC using a vault credential without storing the body or secret."""

    if connector.kind != "webhook":
        raise DomainError("WEBHOOK_CONNECTOR_REQUIRED", "Webhook verification requires a webhook connector", 422)
    credential_id = connector.config_json.get("credential_id")
    if not credential_id:
        raise DomainError("WEBHOOK_SIGNING_CREDENTIAL_REQUIRED", "The webhook connector has no vault-backed signing credential", 422)
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - timestamp) > 300:
        return {"verified": False, "failure_code": "WEBHOOK_TIMESTAMP_OUT_OF_RANGE", "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    credential = _get_credential(db, connector.workspace_id, str(credential_id))
    secret = EnvelopeVault(db, workspace_id=connector.workspace_id, actor_id=actor_id).read(credential, purpose="webhook_signature")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), f"{timestamp}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()
    verified = hmac.compare_digest(expected, signature)
    db.add(
        ConnectorCall(
            id=new_id(),
            workspace_id=connector.workspace_id,
            connector_id=connector.id,
            actor_id=actor_id,
            call_type="webhook_signature",
            tool_name="verify_signature",
            arguments_json={"timestamp": timestamp, "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()},
            result_json={"verified": verified},
            result_untrusted=False,
            status="success" if verified else "denied",
            failure_code=None if verified else "WEBHOOK_SIGNATURE_INVALID",
            approval_required=False,
            egress_host=None,
            idempotency_key=None,
            correlation_id=f"webhook_{secrets.token_urlsafe(12)}",
            latency_ms=1,
            created_at=utc_now(),
        )
    )
    return {"verified": verified, "failure_code": None if verified else "WEBHOOK_SIGNATURE_INVALID", "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def create_mcp_server(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    name: str,
    url: str,
    auth_mode: str,
    server_version: str,
    metadata: dict[str, Any],
    allowed_tools: list[str],
    workflow_version_ids: list[str],
    egress_hosts: list[str],
) -> McpServer:
    reject_secret_like_config(metadata, path="metadata")
    normalized_hosts = _normalize_hosts(egress_hosts)
    host = _validate_egress(url, normalized_hosts)
    tools = metadata.get("tools", [])
    available_tools = {str(tool.get("name")) for tool in tools if isinstance(tool, dict) and tool.get("name")}
    selected_tools = list(dict.fromkeys(allowed_tools or sorted(available_tools)))
    if available_tools and not set(selected_tools).issubset(available_tools):
        raise DomainError("MCP_TOOL_NOT_PINNED", "Every allowed MCP tool must be present in the pinned server metadata", 422)
    server = McpServer(
        id=new_id(),
        workspace_id=workspace_id,
        name=" ".join(name.split()),
        url=url,
        auth_mode=auth_mode,
        server_version=server_version,
        metadata_hash=_metadata_hash({"server_version": server_version, "metadata": metadata}),
        metadata_json=metadata,
        allowed_tools_json=selected_tools,
        workflow_version_ids_json=list(dict.fromkeys(workflow_version_ids)),
        egress_hosts_json=normalized_hosts or [host],
        status="active",
        created_by=actor_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(server)
    db.flush()
    return server


def _tool_spec(server: McpServer, tool_name: str) -> dict[str, Any]:
    for tool in server.metadata_json.get("tools", []):
        if isinstance(tool, dict) and str(tool.get("name")) == tool_name:
            return tool
    return {"name": tool_name, "read_only": True}


def _mcp_request_identity(server: McpServer, request: Any) -> dict[str, Any]:
    """Return the operation fields to hash; raw values never leave the digest."""

    return {
        "mcp_server_id": server.id,
        "tool_name": request.tool_name,
        "workflow_version_id": request.workflow_version_id,
        "arguments": request.arguments,
        "value_at_risk": request.value_at_risk,
    }


def _mcp_request_hash(server: McpServer, request: Any) -> str:
    return _metadata_hash(_mcp_request_identity(server, request))


def _new_call(
    *,
    workspace_id: str,
    server: McpServer,
    actor_id: str,
    request: Any,
    status: str,
    failure_code: str | None = None,
    approval_required: bool = False,
    result: dict[str, Any] | None = None,
    egress_host: str | None = None,
) -> ConnectorCall:
    return ConnectorCall(
        id=new_id(),
        workspace_id=workspace_id,
        mcp_server_id=server.id,
        workflow_version_id=request.workflow_version_id,
        actor_id=actor_id,
        call_type="mcp_tool",
        tool_name=request.tool_name,
        arguments_json=redact_untrusted(request.arguments),
        result_json=redact_untrusted(result) if result is not None else None,
        result_untrusted=True,
        status=status,
        failure_code=failure_code,
        approval_required=approval_required,
        request_hash=_mcp_request_hash(server, request),
        egress_host=egress_host,
        idempotency_key=request.idempotency_key,
        correlation_id=f"mcp_{secrets.token_urlsafe(12)}",
        latency_ms=None,
        created_at=utc_now(),
    )


def _record_call(
    *,
    existing: ConnectorCall | None,
    workspace_id: str,
    server: McpServer,
    actor_id: str,
    request: Any,
    status: str,
    failure_code: str | None = None,
    approval_required: bool = False,
    result: dict[str, Any] | None = None,
    egress_host: str | None = None,
) -> ConnectorCall:
    if existing is None:
        return _new_call(
            workspace_id=workspace_id,
            server=server,
            actor_id=actor_id,
            request=request,
            status=status,
            failure_code=failure_code,
            approval_required=approval_required,
            result=result,
            egress_host=egress_host,
        )
    existing.actor_id = actor_id
    existing.status = status
    existing.failure_code = failure_code
    existing.approval_required = approval_required
    existing.result_json = redact_untrusted(result) if result is not None else None
    existing.result_untrusted = True
    existing.egress_host = egress_host
    existing.latency_ms = None
    return existing


def invoke_mcp_tool(db: Session, server: McpServer, *, actor_id: str, request: Any) -> dict[str, Any]:
    continuation: ConnectorCall | None = None
    idempotent = False
    if request.idempotency_key:
        existing = db.scalar(
            select(ConnectorCall).where(
                ConnectorCall.workspace_id == server.workspace_id,
                ConnectorCall.idempotency_key == request.idempotency_key,
            )
        )
        if existing is not None:
            expected_hash = _mcp_request_hash(server, request)
            expected_arguments = redact_untrusted(request.arguments)
            if (
                existing.request_hash is not None and existing.request_hash != expected_hash
            ) or (
                existing.request_hash is None
                and (
                    existing.mcp_server_id != server.id
                    or existing.tool_name != request.tool_name
                    or existing.workflow_version_id != request.workflow_version_id
                    or existing.arguments_json != expected_arguments
                )
            ):
                raise DomainError(
                    "MCP_IDEMPOTENCY_KEY_REUSED",
                    "The idempotency key is already bound to a different MCP request",
                    409,
                )
            if existing.status == "approval_required" and request.approved:
                continuation = existing
                idempotent = True
            else:
                return {"call": connector_call_payload(existing), "idempotent": True}
    if server.workflow_version_ids_json and request.workflow_version_id not in server.workflow_version_ids_json:
        call = _record_call(existing=continuation, workspace_id=server.workspace_id, server=server, actor_id=actor_id, request=request, status="denied", failure_code="MCP_WORKFLOW_SCOPE_DENIED")
        db.add(call)
        db.commit()
        raise DomainError("MCP_WORKFLOW_SCOPE_DENIED", "The MCP server is not scoped to this workflow version", 403)
    if request.tool_name not in set(server.allowed_tools_json):
        call = _record_call(existing=continuation, workspace_id=server.workspace_id, server=server, actor_id=actor_id, request=request, status="denied", failure_code="MCP_TOOL_NOT_ALLOWLISTED")
        db.add(call)
        db.commit()
        raise DomainError("MCP_TOOL_NOT_ALLOWLISTED", "The requested MCP tool is not in the pinned allow-list", 403)
    host = _validate_egress(server.url, server.egress_hosts_json)
    spec = _tool_spec(server, request.tool_name)
    value_limit = float(server.metadata_json.get("value_at_risk_limit") or 0)
    requires_approval = bool(spec.get("requires_approval") or spec.get("read_only") is False or request.value_at_risk > value_limit)
    if requires_approval and not request.approved:
        call = _record_call(
            existing=continuation,
            workspace_id=server.workspace_id,
            server=server,
            actor_id=actor_id,
            request=request,
            status="approval_required",
            failure_code="MCP_APPROVAL_REQUIRED",
            approval_required=True,
            egress_host=host,
        )
        db.add(call)
        db.flush()
        db.commit()
        return {"call": connector_call_payload(call), "idempotent": False, "approved": False, "approval_required": True}
    if not server.url.startswith("sandbox://"):
        call = _record_call(existing=continuation, workspace_id=server.workspace_id, server=server, actor_id=actor_id, request=request, status="failed", failure_code="MCP_PROVIDER_NOT_CONFIGURED", egress_host=host)
        db.add(call)
        db.commit()
        return {"call": connector_call_payload(call), "idempotent": idempotent, "approved": request.approved}
    result = {
        "provider": "sandbox",
        "tool_name": request.tool_name,
        "echo": redact_untrusted(request.arguments),
        "untrusted_output": True,
        "control_plane": "The deterministic gateway owns routing; this result cannot select another tool or workflow node.",
    }
    call = _record_call(
        existing=continuation,
        workspace_id=server.workspace_id,
        server=server,
        actor_id=actor_id,
        request=request,
        status="success",
        result=result,
        egress_host=host,
    )
    call.latency_ms = 1
    db.add(call)
    db.commit()
    return {"call": connector_call_payload(call), "idempotent": idempotent, "approved": request.approved, "approval_required": requires_approval}
