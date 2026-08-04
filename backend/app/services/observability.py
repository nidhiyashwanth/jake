"""OpenTelemetry/Langfuse and Sentry-compatible seams for runtime evidence.

The business timeline remains in the existing execution tables. This module
only emits spans/log correlation and exposes provider health; it is not a
second trace database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from datetime import timedelta
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import get_settings
from app.models import Execution, RuntimeWorkerHeartbeat, utc_now
from sqlalchemy import func, select


logger = logging.getLogger("app.observability")
_initialized = False
_tracer: Any = None
_sentry: Any = None

_SECRET_KEY = re.compile(r"(?i)(password|secret|token|api[_-]?key|authorization|private[_-]?key|client[_-]?secret|credential)")
_PII_KEY = re.compile(r"(?i)^(email|phone|mobile|ssn|tax[_-]?id|address)$")
_BEARER = re.compile(r"(?i)^bearer\s+")
_PRIVATE_MATERIAL = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


def redact_untrusted(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe redacted view for inspectors, logs, and traces."""

    if key and _SECRET_KEY.search(key):
        return "[REDACTED]"
    if key and _PII_KEY.search(key):
        return "[PII REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): redact_untrusted(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_untrusted(item) for item in value]
    if isinstance(value, str):
        if _PRIVATE_MATERIAL.search(value) or _BEARER.search(value):
            return "[REDACTED]"
        return value[:20_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:20_000]


def trace_context(correlation_id: str, span_key: str) -> dict[str, str]:
    trace_id = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()[:32]
    span_id = hashlib.sha256(f"{trace_id}:{span_key}".encode("utf-8")).hexdigest()[:16]
    return {"trace_id": trace_id, "span_id": span_id, "correlation_id": correlation_id}


def _initialize() -> None:
    global _initialized, _tracer, _sentry
    if _initialized:
        return
    settings = get_settings()
    endpoint = settings.langfuse_otel_endpoint or settings.otel_exporter_otlp_endpoint
    if endpoint:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            headers: dict[str, str] = {}
            if settings.langfuse_public_key and settings.langfuse_secret_key:
                auth = base64.b64encode(f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode("utf-8")).decode("ascii")
                headers["Authorization"] = f"Basic {auth}"
            provider = TracerProvider(resource=Resource.create({"service.name": "ai-ops-platform", "deployment.environment": settings.environment}))
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers)))
            trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer("ai-ops-platform.runtime", "i01")
        except Exception:
            logger.warning("observability trace exporter unavailable; structured runtime logs remain enabled")
    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, send_default_pii=False, traces_sample_rate=0.0)
            _sentry = sentry_sdk
        except Exception:
            logger.warning("error reporting provider unavailable; degraded-mode signals remain enabled")
    _initialized = True


def observability_status() -> dict[str, Any]:
    _initialize()
    settings = get_settings()
    langfuse_configured = bool(settings.langfuse_otel_endpoint and settings.langfuse_public_key and settings.langfuse_secret_key)
    otel_configured = bool(settings.langfuse_otel_endpoint or settings.otel_exporter_otlp_endpoint)
    sentry_configured = bool(settings.sentry_dsn and _sentry is not None)
    degraded_signals: list[str] = []
    if not otel_configured:
        degraded_signals.append("otel_exporter_not_configured")
    if not langfuse_configured:
        degraded_signals.append("langfuse_sink_not_configured")
    if settings.sentry_dsn and not sentry_configured:
        degraded_signals.append("error_reporting_unavailable")
    return {
        "status": "degraded" if degraded_signals else "healthy",
        "trace": {"provider": "langfuse" if langfuse_configured else ("otel" if otel_configured else "structured_log"), "configured": otel_configured},
        "langfuse": {"configured": langfuse_configured, "host_configured": bool(settings.langfuse_host)},
        "error_reporting": {"provider": "sentry-compatible", "configured": sentry_configured},
        "redaction": {"status": "healthy", "policy_version": "redaction.v1", "pii_and_secret_fields_hidden": True},
        "degraded_signals": degraded_signals,
    }


def emit_runtime_event(event_type: str, *, correlation_id: str, span_key: str, payload: Mapping[str, Any] | None = None) -> dict[str, str]:
    _initialize()
    context = trace_context(correlation_id, span_key)
    safe_payload = redact_untrusted(dict(payload or {}))
    record = {"event": "runtime.event", "event_type": event_type, **context, "payload": safe_payload}
    logger.info(json.dumps(record, sort_keys=True, ensure_ascii=True))
    if _tracer is not None:
        with _tracer.start_as_current_span(f"runtime.{event_type}") as span:
            span.set_attribute("runtime.trace_id", context["trace_id"])
            span.set_attribute("runtime.correlation_id", correlation_id)
            span.set_attribute("runtime.event_type", event_type)
    return context


def capture_exception(error: BaseException, *, correlation_id: str | None = None) -> None:
    _initialize()
    logger.error(json.dumps({"event": "runtime.error", "error_type": type(error).__name__, "correlation_id": correlation_id}, sort_keys=True))
    if _sentry is not None:
        _sentry.capture_exception(error)


def record_worker_heartbeat(db: Any, *, workspace_id: str, worker_id: str, processed_count: int, status: str = "healthy", last_error: str | None = None) -> RuntimeWorkerHeartbeat:
    heartbeat = db.scalar(
        select(RuntimeWorkerHeartbeat).where(
            RuntimeWorkerHeartbeat.workspace_id == workspace_id,
            RuntimeWorkerHeartbeat.worker_id == worker_id,
        )
    )
    if heartbeat is None:
        heartbeat = RuntimeWorkerHeartbeat(
            workspace_id=workspace_id,
            worker_id=worker_id,
            status=status,
            last_seen_at=utc_now(),
            processed_count=processed_count,
            last_error=redact_untrusted({"error": last_error}).get("error") if last_error else None,
            trace_id=trace_context(worker_id, f"worker:{workspace_id}")["trace_id"],
        )
        db.add(heartbeat)
    else:
        heartbeat.status = status
        heartbeat.last_seen_at = utc_now()
        heartbeat.processed_count = processed_count
        heartbeat.last_error = redact_untrusted({"error": last_error}).get("error") if last_error else None
    db.flush()
    return heartbeat


def runtime_observability(db: Any, *, workspace_id: str) -> dict[str, Any]:
    base = observability_status()
    now = utc_now()
    heartbeat = db.scalar(
        select(RuntimeWorkerHeartbeat)
        .where(RuntimeWorkerHeartbeat.workspace_id == workspace_id)
        .order_by(RuntimeWorkerHeartbeat.last_seen_at.desc())
        .limit(1)
    )
    queued = int(db.scalar(select(func.count(Execution.id)).where(Execution.workspace_id == workspace_id, Execution.status.in_(("queued", "running")))) or 0)
    failed = int(db.scalar(select(func.count(Execution.id)).where(Execution.workspace_id == workspace_id, Execution.status.in_(("failed", "dead_letter")))) or 0)
    worker_status = "unknown"
    if heartbeat is not None:
        worker_status = heartbeat.status if heartbeat.last_seen_at >= now - timedelta(seconds=20) else "degraded"
    signals = list(base["degraded_signals"])
    if worker_status in {"unknown", "degraded"}:
        signals.append("runtime_worker_heartbeat_stale")
    if failed > 0:
        signals.append("failed_or_dead_letter_runs_present")
    return {
        **base,
        "status": "degraded" if signals else "healthy",
        "runtime_worker": {
            "status": worker_status,
            "worker_id": heartbeat.worker_id if heartbeat else None,
            "last_seen_at": heartbeat.last_seen_at.isoformat() if heartbeat else None,
            "processed_count": heartbeat.processed_count if heartbeat else 0,
            "last_error": heartbeat.last_error if heartbeat else None,
        },
        "queue": {"queued_or_running": queued, "failed_or_dead_letter": failed},
        "degraded_signals": sorted(set(signals)),
    }


@contextmanager
def runtime_span(name: str, *, correlation_id: str, span_key: str) -> Iterator[dict[str, str]]:
    """Provide one correlation context without persisting a custom span row."""

    context = trace_context(correlation_id, span_key)
    _initialize()
    if _tracer is None:
        yield context
        return
    with _tracer.start_as_current_span(name) as span:
        span.set_attribute("runtime.trace_id", context["trace_id"])
        span.set_attribute("runtime.correlation_id", correlation_id)
        yield context
