from typing import Any

from sqlalchemy.orm import Session

from app.errors import DomainError
from app.services.audit import append_audit_log


CANONICAL_ROLES = frozenset({"owner", "admin", "builder", "operator", "viewer", "auditor"})
ROLE_ALIASES = {"reviewer": "operator"}
VALID_ROLES = CANONICAL_ROLES | ROLE_ALIASES.keys()

GENERAL_READ_ACTIONS = frozenset({"workspace.read", "vendor.read", "review.read"})
DISCOVERY_READ_ACTIONS = frozenset({"discovery.read", "baseline.read", "score.read"})
DISCOVERY_BUILD_ACTIONS = frozenset(
    {
        "discovery.create",
        "discovery.update",
        "discovery.interview.ingest",
        "baseline.create",
        "baseline.update",
        "score.compute",
    }
)
BASELINE_SIGN_ACTION = "baseline.sign"
AUDIT_READ_ACTION = "audit.read"
WRITE_ACTIONS = frozenset(
    {
        "vendor.create",
        "document.upload",
        "document.verify",
        "review.update",
    }
)
MEMBERSHIP_ACTIONS = frozenset({"member.read", "member.invite", "member.role_change", "member.disable"})

ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "owner": (
        GENERAL_READ_ACTIONS
        | DISCOVERY_READ_ACTIONS
        | DISCOVERY_BUILD_ACTIONS
        | {BASELINE_SIGN_ACTION, AUDIT_READ_ACTION}
        | WRITE_ACTIONS
        | MEMBERSHIP_ACTIONS
        | {"workspace.manage"}
    ),
    "admin": (
        GENERAL_READ_ACTIONS
        | DISCOVERY_READ_ACTIONS
        | DISCOVERY_BUILD_ACTIONS
        | {BASELINE_SIGN_ACTION, AUDIT_READ_ACTION}
        | WRITE_ACTIONS
        | MEMBERSHIP_ACTIONS
        | {"workspace.manage"}
    ),
    "builder": (
        GENERAL_READ_ACTIONS
        | DISCOVERY_READ_ACTIONS
        | DISCOVERY_BUILD_ACTIONS
        | {"vendor.create", "document.upload", "document.verify"}
    ),
    "operator": GENERAL_READ_ACTIONS | {"vendor.create", "document.upload", "document.verify", "review.update"},
    "viewer": GENERAL_READ_ACTIONS | DISCOVERY_READ_ACTIONS,
    "auditor": frozenset({"workspace.read", "vendor.read", "audit.read", "member.read"}) | DISCOVERY_READ_ACTIONS,
}


def normalize_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)


def role_allows(role: str, action: str) -> bool:
    return action in ROLE_ACTIONS.get(normalize_role(role), frozenset())


def authorize(
    db: Session,
    context: Any,
    action: str,
    *,
    target_type: str = "permission",
    target_id: str | None = None,
) -> None:
    if role_allows(context.role, action):
        return

    append_audit_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        action="authorization.denied",
        target_type=target_type,
        target_id=target_id or action,
        after={"requested_action": action, "role": context.role},
    )
    db.commit()
    raise DomainError("AUTHORIZATION_DENIED", f"Role {context.role} cannot perform {action}", 403)


def require_workspace(context: Any, workspace_id: str, db: Session) -> None:
    if workspace_id == context.workspace_id:
        return
    append_audit_log(
        db,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        action="authorization.denied",
        target_type="workspace",
        target_id=workspace_id,
        after={"requested_action": "workspace.context", "active_workspace_id": context.workspace_id},
    )
    db.commit()
    raise DomainError("WORKSPACE_CONTEXT_MISMATCH", "The requested workspace is not active in this session", 403)
