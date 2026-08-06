from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Protocol

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, set_workspace_scope
from app.errors import DomainError
from app.models import (
    AuthSession,
    Membership,
    Organization,
    User,
    Workspace,
    WorkspaceContext,
    utc_now,
)
from app.services.audit import append_audit_log


@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str | None
    workspace_id: str
    development_fallback: bool = False


@dataclass(frozen=True)
class RequestContext:
    user_id: str
    user_email: str
    user_name: str
    organization_id: str
    workspace_id: str
    workspace_name: str
    workspace_environment: str
    delivery_mode: str
    handoff_mode: str
    membership_id: str
    role: str
    session_id: str | None
    development_fallback: bool = False


class AuthProvider(Protocol):
    def authenticate(self, request: Request, db: Session) -> Principal:
        """Return an authenticated principal without making authorization decisions."""


def _request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_auth_event(
    db: Session,
    request: Request,
    *,
    action: str,
    target_id: str,
    workspace_id: str | None = None,
    actor_id: str | None = None,
    after: dict[str, object] | None = None,
) -> None:
    """Persist auth events when the governance schema exists without leaking token material."""

    try:
        append_audit_log(
            db,
            action=action,
            target_type="authentication",
            target_id=target_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            after=after,
            ip_address=_request_ip(request),
        )
        db.commit()
    except SQLAlchemyError:
        # The health endpoint must remain useful before the first migration. Auth
        # failures are still returned safely if the governance table is absent.
        db.rollback()


def _authentication_error(db: Session, request: Request, code: str, message: str, target_id: str) -> DomainError:
    _safe_auth_event(db, request, action="auth.denied", target_id=target_id, after={"code": code})
    return DomainError(code, message, 401)


class DevelopmentIdentityProvider:
    """Local-only provider; it is deliberately rejected by production settings."""

    def authenticate(self, request: Request, db: Session) -> Principal:
        settings = get_settings()
        authorization = request.headers.get("authorization", "")
        if not authorization:
            if not settings.allow_development_identity:
                raise _authentication_error(
                    db,
                    request,
                    "AUTHENTICATION_REQUIRED",
                    "A bearer session is required when development identity is disabled",
                    "anonymous",
                )
            return Principal(
                user_id=settings.dev_default_user_id,
                session_id=None,
                workspace_id=settings.dev_default_workspace_id,
                development_fallback=True,
            )

        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            raise _authentication_error(
                db,
                request,
                "AUTHENTICATION_INVALID",
                "Use an Authorization: Bearer <session> header",
                "malformed",
            )

        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash_session_token(token.strip())))
        if session is None:
            raise _authentication_error(db, request, "AUTHENTICATION_INVALID", "The session is not valid", "unknown")

        now = utc_now()
        if session.revoked_at is not None:
            set_workspace_scope(db, session.workspace_id)
            _safe_auth_event(
                db,
                request,
                action="auth.session_rejected",
                target_id=session.id,
                workspace_id=session.workspace_id,
                actor_id=session.user_id,
                after={"reason": "revoked"},
            )
            raise DomainError("SESSION_REVOKED", "The session has been revoked", 401)
        if session.expires_at <= now:
            set_workspace_scope(db, session.workspace_id)
            _safe_auth_event(
                db,
                request,
                action="auth.session_rejected",
                target_id=session.id,
                workspace_id=session.workspace_id,
                actor_id=session.user_id,
                after={"reason": "expired"},
            )
            raise DomainError("SESSION_EXPIRED", "The session has expired", 401)

        session.last_seen_at = now
        return Principal(user_id=session.user_id, session_id=session.id, workspace_id=session.workspace_id)


class OidcJwtIdentityProvider:
    """Explicit seam for a verified OIDC/JWT adapter owned by the deployment."""

    def authenticate(self, request: Request, db: Session) -> Principal:
        raise DomainError(
            "AUTH_PROVIDER_NOT_CONFIGURED",
            "The configured OIDC/JWT provider needs a verified adapter before this environment can serve traffic",
            503,
        )


def get_auth_provider() -> AuthProvider:
    provider = get_settings().auth_provider
    if provider == "development":
        return DevelopmentIdentityProvider()
    if provider == "oidc_jwt":
        return OidcJwtIdentityProvider()
    raise DomainError("AUTH_PROVIDER_NOT_CONFIGURED", f"Unsupported auth provider: {provider}", 503)


def _active_membership(db: Session, user_id: str, workspace_id: str) -> Membership | None:
    return db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.workspace_id == workspace_id,
        )
    )


def _reject_disabled_membership(db: Session, request: Request, membership: Membership, workspace_id: str) -> None:
    set_workspace_scope(db, workspace_id)
    _safe_auth_event(
        db,
        request,
        action="auth.membership_rejected",
        target_id=membership.id,
        workspace_id=workspace_id,
        actor_id=membership.user_id,
        after={"reason": "disabled"},
    )
    raise DomainError("MEMBERSHIP_DISABLED", "The workspace membership is disabled", 403)


def resolve_request_context(request: Request, db: Session) -> RequestContext:
    principal = get_auth_provider().authenticate(request, db)
    requested_workspace_id = request.headers.get("x-workspace-id")
    workspace_id = requested_workspace_id or principal.workspace_id

    membership = _active_membership(db, principal.user_id, workspace_id)
    if membership is None:
        if requested_workspace_id:
            _safe_auth_event(
                db,
                request,
                action="auth.context_denied",
                target_id=workspace_id,
                actor_id=principal.user_id,
                after={"reason": "no_membership"},
            )
            raise DomainError("WORKSPACE_ACCESS_DENIED", "The user is not a member of this workspace", 403)
        raise DomainError("TENANCY_NOT_INITIALIZED", "The default development workspace is not initialized", 503)
    if membership.status != "active":
        _reject_disabled_membership(db, request, membership, workspace_id)

    user = db.get(User, principal.user_id)
    workspace = db.get(Workspace, workspace_id)
    if user is None or workspace is None:
        raise DomainError("TENANCY_NOT_INITIALIZED", "The authenticated tenancy records are incomplete", 503)

    if principal.session_id:
        session = db.get(AuthSession, principal.session_id)
        if session is None or session.user_id != user.id:
            raise DomainError("AUTHENTICATION_INVALID", "The session context is not valid", 401)

    set_workspace_scope(db, workspace_id)
    context = RequestContext(
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        workspace_environment=workspace.environment,
        delivery_mode=workspace.delivery_mode,
        handoff_mode=workspace.handoff_mode,
        membership_id=membership.id,
        role=membership.role,
        session_id=principal.session_id,
        development_fallback=principal.development_fallback,
    )
    db.info["request_context"] = context
    return context


def get_request_context(request: Request, db: Session = Depends(get_db)) -> RequestContext:
    return resolve_request_context(request, db)


def get_scoped_db(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> Session:
    set_workspace_scope(db, context.workspace_id)
    db.info["request_context"] = context
    return db


def current_context(db: Session) -> RequestContext:
    context = db.info.get("request_context")
    if not isinstance(context, RequestContext):
        raise DomainError("REQUEST_CONTEXT_MISSING", "A workspace request context is required", 500)
    return context


def create_development_session(
    db: Session,
    request: Request,
    *,
    email: str,
    name: str,
    organization_name: str,
    workspace_name: str,
) -> dict[str, object]:
    settings = get_settings()
    if settings.environment.casefold() not in {"development", "dev", "test"} or settings.auth_provider != "development":
        raise DomainError("DEVELOPMENT_AUTH_DISABLED", "The local development login is not available in this environment", 403)

    normalized_email = email.strip().casefold()
    organization = db.scalar(select(Organization).where(Organization.name == organization_name))
    organization_created = organization is None
    if organization is None:
        organization = Organization(name=organization_name, kind="customer")
        db.add(organization)
        db.flush()

    workspace = db.scalar(
        select(Workspace).where(
            Workspace.organization_id == organization.id,
            Workspace.name == workspace_name,
        )
    )
    workspace_created = workspace is None
    if workspace is None:
        workspace = Workspace(
            organization_id=organization.id,
            name=workspace_name,
            environment="development",
            delivery_mode="delivery",
            handoff_mode="operator",
        )
        db.add(workspace)
        db.flush()

    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(email=normalized_email, name=name.strip())
        db.add(user)
        db.flush()
    elif name.strip() and user.name != name.strip():
        user.name = name.strip()

    membership = _active_membership(db, user.id, workspace.id)
    if membership is not None and membership.status != "active":
        _reject_disabled_membership(db, request, membership, workspace.id)
    if membership is None:
        if not workspace_created:
            _safe_auth_event(
                db,
                request,
                action="auth.dev_login_denied",
                target_id=workspace.id,
                actor_id=user.id,
                after={"reason": "no_membership"},
            )
            raise DomainError("WORKSPACE_ACCESS_DENIED", "Invite the user before using this development workspace", 403)
        membership = Membership(user_id=user.id, workspace_id=workspace.id, role="owner", status="active")
        db.add(membership)
        db.flush()

    raw_token = secrets.token_urlsafe(32)
    now = utc_now()
    session = AuthSession(
        user_id=user.id,
        workspace_id=workspace.id,
        token_hash=_hash_session_token(raw_token),
        expires_at=now + timedelta(minutes=settings.session_ttl_minutes),
        last_seen_at=now,
        ip_address=_request_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
    )
    db.add(session)
    db.flush()
    set_workspace_scope(db, workspace.id)
    db.add(WorkspaceContext(session_id=session.id, user_id=user.id, workspace_id=workspace.id))
    append_audit_log(
        db,
        action="auth.dev_login",
        target_type="user",
        target_id=user.id,
        workspace_id=workspace.id,
        actor_id=user.id,
        after={"session_id": session.id, "role": membership.role, "development_only": True},
        ip_address=_request_ip(request),
    )
    db.commit()
    return {
        "token": raw_token,
        "session": session,
        "user": user,
        "workspace": workspace,
        "membership": membership,
        "organization_created": organization_created,
    }


def switch_session_workspace(db: Session, request: Request, context: RequestContext, workspace_id: str) -> RequestContext:
    if context.session_id is None:
        raise DomainError("SESSION_REQUIRED", "Log in to switch the active workspace", 401)

    target_membership = _active_membership(db, context.user_id, workspace_id)
    if target_membership is None:
        raise DomainError("WORKSPACE_ACCESS_DENIED", "The user is not a member of this workspace", 403)
    if target_membership.status != "active":
        _reject_disabled_membership(db, request, target_membership, workspace_id)

    session = db.get(AuthSession, context.session_id)
    target_workspace = db.get(Workspace, workspace_id)
    if session is None or target_workspace is None:
        raise DomainError("SESSION_INVALID", "The active session is not valid", 401)

    now = utc_now()
    append_audit_log(
        db,
        action="auth.context_changed",
        target_type="workspace",
        target_id=workspace_id,
        workspace_id=context.workspace_id,
        actor_id=context.user_id,
        before={"workspace_id": context.workspace_id},
        after={"workspace_id": workspace_id, "session_id": session.id},
        ip_address=_request_ip(request),
    )
    db.execute(
        update(WorkspaceContext)
        .where(
            WorkspaceContext.session_id == session.id,
            WorkspaceContext.deactivated_at.is_(None),
        )
        .values(deactivated_at=now)
    )
    session.workspace_id = workspace_id
    db.add(WorkspaceContext(session_id=session.id, user_id=context.user_id, workspace_id=workspace_id))
    db.commit()

    set_workspace_scope(db, workspace_id)
    append_audit_log(
        db,
        action="auth.context_activated",
        target_type="workspace",
        target_id=workspace_id,
        workspace_id=workspace_id,
        actor_id=context.user_id,
        after={"session_id": session.id},
        ip_address=_request_ip(request),
    )
    db.commit()

    user = db.get(User, context.user_id)
    if user is None:
        raise DomainError("TENANCY_NOT_INITIALIZED", "The authenticated user no longer exists", 503)
    return RequestContext(
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        organization_id=target_workspace.organization_id,
        workspace_id=target_workspace.id,
        workspace_name=target_workspace.name,
        workspace_environment=target_workspace.environment,
        delivery_mode=target_workspace.delivery_mode,
        handoff_mode=target_workspace.handoff_mode,
        membership_id=target_membership.id,
        role=target_membership.role,
        session_id=session.id,
    )
