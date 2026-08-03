"""Deterministic workflow-definition, DAG, and publish-gate services.

This module owns workflow control-plane decisions.  A model may be referenced by
an ``llm`` node, but it cannot decide graph validity, version hashes,
authorization, evaluation binding, or persistence transitions.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import (
    Baseline,
    ModelConfig,
    Prompt,
    PromptVersion,
    Process,
    Workflow,
    WorkflowEdge,
    WorkflowEvaluationResult,
    WorkflowNode,
    WorkflowThreshold,
    WorkflowVersion,
    new_id,
    utc_now,
)
from app.schemas import (
    ModelConfigCreate,
    ApproveNodeConfig,
    ClassifyNodeConfig,
    ExtractNodeConfig,
    FetchNodeConfig,
    HaltNodeConfig,
    LlmNodeConfig,
    NotifyNodeConfig,
    ParseNodeConfig,
    PromptCreate,
    PromptVersionCreate,
    RuleNodeConfig,
    ScoreNodeConfig,
    TriggerNodeConfig,
    ToolNodeConfig,
    WorkflowCreate,
    WorkflowEvaluationCreate,
    WorkflowSpecInput,
    WorkflowVersionCreate,
    WorkflowVersionPatch,
)
from app.services.audit import append_audit_log


CURRENT_WORKFLOW_SCHEMA_VERSION = "workflow.v1"
SUPPORTED_WORKFLOW_SCHEMA_VERSIONS = frozenset({CURRENT_WORKFLOW_SCHEMA_VERSION, "1", 1})
WORKFLOW_NODE_TYPES = frozenset(
    {
        "trigger",
        "fetch",
        "parse",
        "classify",
        "extract",
        "rule",
        "score",
        "llm",
        "tool",
        "approve",
        "notify",
        "halt",
    }
)
NODE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SECRET_PARAM_KEYS = frozenset({"api_key", "apikey", "token", "secret", "password", "client_secret"})
NODE_CONFIG_MODELS = {
    "trigger": TriggerNodeConfig,
    "fetch": FetchNodeConfig,
    "parse": ParseNodeConfig,
    "classify": ClassifyNodeConfig,
    "extract": ExtractNodeConfig,
    "rule": RuleNodeConfig,
    "score": ScoreNodeConfig,
    "llm": LlmNodeConfig,
    "tool": ToolNodeConfig,
    "approve": ApproveNodeConfig,
    "notify": NotifyNodeConfig,
    "halt": HaltNodeConfig,
}


def canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible value reproducibly for version hashes."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class WorkflowValidation:
    normalized_spec: dict[str, Any]
    definition_hash: str
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "definition_hash": self.definition_hash,
            "issues": [issue.as_dict() for issue in self.issues],
            "schema_version": self.normalized_spec.get("schema_version"),
        }


def _issue(issues: list[ValidationIssue], code: str, path: str, message: str) -> None:
    issues.append(ValidationIssue(code=code, path=path, message=message))


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=False)
    return value


def migrate_workflow_spec(payload: WorkflowSpecInput | dict[str, Any]) -> dict[str, Any]:
    """Normalize the v1 wire shape and the original draft-graph aliases.

    The migration is intentionally pure and forward-compatible: old drafts can
    be loaded and re-saved without changing their meaning, while an unknown
    schema version is rejected before any write.
    """

    raw = _model_dump(payload)
    if not isinstance(raw, dict):
        raise DomainError("WORKFLOW_SCHEMA_INVALID", "Workflow specification must be a JSON object", 422)

    raw_version = raw.get("schema_version", raw.get("version", CURRENT_WORKFLOW_SCHEMA_VERSION))
    if raw_version not in SUPPORTED_WORKFLOW_SCHEMA_VERSIONS:
        raise DomainError(
            "WORKFLOW_SCHEMA_UNSUPPORTED",
            f"Workflow schema {raw_version!r} is not supported; use {CURRENT_WORKFLOW_SCHEMA_VERSION}",
            422,
            details={"supported_versions": [CURRENT_WORKFLOW_SCHEMA_VERSION]},
        )

    raw_nodes = raw.get("nodes", [])
    raw_edges = raw.get("edges", [])
    raw_thresholds = raw.get("thresholds", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list) or not isinstance(raw_thresholds, list):
        raise DomainError(
            "WORKFLOW_SCHEMA_INVALID",
            "nodes, edges, and thresholds must be arrays",
            422,
        )

    nodes: list[dict[str, Any]] = []
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            raise DomainError(
                "WORKFLOW_SCHEMA_INVALID",
                f"nodes[{index}] must be an object",
                422,
                details={"path": f"nodes[{index}]"},
            )
        node = dict(raw_node)
        key = node.get("key", node.get("node_key", node.get("id")))
        node_type = node.get("type", node.get("node_type"))
        config = node.get("config", node.get("config_json", {}))
        label = node.get("label", key or f"Node {index + 1}")
        if not isinstance(key, str) or not isinstance(node_type, str) or not isinstance(label, str):
            raise DomainError(
                "WORKFLOW_SCHEMA_INVALID",
                f"nodes[{index}] requires string key, type, and label",
                422,
                details={"path": f"nodes[{index}]"},
            )
        if not isinstance(config, dict):
            raise DomainError(
                "WORKFLOW_SCHEMA_INVALID",
                f"nodes[{index}].config must be an object",
                422,
                details={"path": f"nodes[{index}].config"},
            )
        normalized_config = dict(config)
        if node_type.strip().casefold() == "trigger":
            normalized_config.setdefault("event", normalized_config.get("trigger_kind"))
        elif node_type.strip().casefold() == "classify":
            normalized_config.setdefault("labels", normalized_config.get("output_labels"))
        elif node_type.strip().casefold() == "extract" and isinstance(normalized_config.get("fields"), list):
            normalized_config["fields"] = {str(field): {"type": "string"} for field in normalized_config["fields"]}
        elif node_type.strip().casefold() == "score":
            normalized_config.setdefault("score_key", normalized_config.get("formula"))
        elif node_type.strip().casefold() == "approve":
            normalized_config.setdefault("reason", normalized_config.get("reason_code"))
        elif node_type.strip().casefold() == "notify":
            normalized_config.setdefault("template", normalized_config.get("template_key"))
        elif node_type.strip().casefold() == "tool":
            normalized_config.setdefault("write", normalized_config.get("writes_external", False))
            normalized_config.setdefault("requires_approval", normalized_config.get("requires_approval", False))
        elif node_type.strip().casefold() == "parse":
            normalized_config.setdefault("schema", normalized_config.get("input_schema", {"type": "object"}))
        nodes.append(
            {
                "key": key.strip(),
                "type": node_type.strip().casefold(),
                "label": " ".join(label.split()),
                "config": normalized_config,
            }
        )

    edges: list[dict[str, Any]] = []
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            raise DomainError(
                "WORKFLOW_SCHEMA_INVALID",
                f"edges[{index}] must be an object",
                422,
                details={"path": f"edges[{index}]"},
            )
        edge = dict(raw_edge)
        from_node = edge.get("from_node", edge.get("from", edge.get("source")))
        to_node = edge.get("to_node", edge.get("to", edge.get("target")))
        if not isinstance(from_node, str) or not isinstance(to_node, str):
            raise DomainError(
                "WORKFLOW_SCHEMA_INVALID",
                f"edges[{index}] requires from_node and to_node strings",
                422,
                details={"path": f"edges[{index}]"},
            )
        condition = edge.get("condition", edge.get("condition_json"))
        if condition is not None and not isinstance(condition, (dict, str)):
            raise DomainError(
                "WORKFLOW_SCHEMA_INVALID",
                f"edges[{index}].condition must be an object, string, or null",
                422,
                details={"path": f"edges[{index}].condition"},
            )
        edges.append({"from_node": from_node.strip(), "to_node": to_node.strip(), "condition": condition})

    incoming_source = {edge["to_node"]: edge["from_node"] for edge in edges}
    for node in nodes:
        config = node["config"]
        if node["type"] != "trigger" and not isinstance(config.get("input"), str):
            source = incoming_source.get(node["key"])
            if source:
                config["input"] = source

    thresholds: list[dict[str, Any]] = []
    for index, raw_threshold in enumerate(raw_thresholds):
        if not isinstance(raw_threshold, dict) or not isinstance(raw_threshold.get("key"), str):
            raise DomainError(
                "WORKFLOW_SCHEMA_INVALID",
                f"thresholds[{index}] requires a key and numeric value",
                422,
                details={"path": f"thresholds[{index}]"},
            )
        thresholds.append(
            {
                "key": raw_threshold["key"].strip(),
                "value": raw_threshold.get("value"),
                "description": raw_threshold.get("description"),
            }
        )

    raw_prompts = raw.get("prompts", [])
    raw_model_configs = raw.get("model_configs", [])
    if not isinstance(raw_prompts, list) or not isinstance(raw_model_configs, list):
        raise DomainError("WORKFLOW_SCHEMA_INVALID", "prompts and model_configs must be arrays", 422)

    prompts = [dict(item) for item in raw_prompts if isinstance(item, dict)]
    model_configs = [dict(item) for item in raw_model_configs if isinstance(item, dict)]

    baseline_id = raw.get("baseline_id")
    metadata = raw.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise DomainError("WORKFLOW_SCHEMA_INVALID", "metadata must be an object", 422)

    return {
        "schema_version": CURRENT_WORKFLOW_SCHEMA_VERSION,
        "nodes": sorted(nodes, key=lambda item: item["key"]),
        "edges": sorted(edges, key=lambda item: (item["from_node"], item["to_node"], canonical_json(item["condition"]))),
        "thresholds": sorted(thresholds, key=lambda item: item["key"]),
        "prompts": sorted(prompts, key=lambda item: (str(item.get("key", "")), int(item.get("version", 0) or 0))),
        "model_configs": sorted(model_configs, key=lambda item: (str(item.get("key", "")), int(item.get("version", 0) or 0))),
        "baseline_id": baseline_id,
        "metadata": metadata,
    }


def _validate_json_schema(schema: Any, path: str, issues: list[ValidationIssue], depth: int = 0) -> None:
    if depth > 12:
        _issue(issues, "OUTPUT_SCHEMA_TOO_DEEP", path, "Output schema nesting cannot exceed 12 levels")
        return
    if not isinstance(schema, dict):
        _issue(issues, "OUTPUT_SCHEMA_INVALID", path, "Output schema must be an object")
        return
    schema_type = schema.get("type")
    allowed_types = {"object", "array", "string", "number", "integer", "boolean", "null"}
    if schema_type not in allowed_types:
        _issue(issues, "OUTPUT_SCHEMA_TYPE_REQUIRED", f"{path}.type", "Output schema requires a supported JSON type")
        return
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        _issue(issues, "OUTPUT_SCHEMA_ENUM_INVALID", f"{path}.enum", "enum must be a non-empty array")
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            _issue(issues, "OUTPUT_SCHEMA_PROPERTIES_INVALID", f"{path}.properties", "properties must be an object")
            properties = {}
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            _issue(issues, "OUTPUT_SCHEMA_REQUIRED_INVALID", f"{path}.required", "required must be an array of strings")
            required = []
        for required_key in required:
            if required_key not in properties:
                _issue(
                    issues,
                    "OUTPUT_SCHEMA_REQUIRED_UNKNOWN",
                    f"{path}.required",
                    f"required field {required_key!r} is not declared in properties",
                )
        for property_name, property_schema in properties.items():
            _validate_json_schema(property_schema, f"{path}.properties.{property_name}", issues, depth + 1)
    elif schema_type == "array":
        if "items" not in schema:
            _issue(issues, "OUTPUT_SCHEMA_ITEMS_REQUIRED", f"{path}.items", "array output schemas require items")
        else:
            _validate_json_schema(schema["items"], f"{path}.items", issues, depth + 1)


def _json_type_matches(expected: str, value: Any) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_structured_output(schema: dict[str, Any], output: Any) -> list[str]:
    """Validate the supported structured-output subset without a model call."""

    schema_issues: list[ValidationIssue] = []
    _validate_json_schema(schema, "$", schema_issues)
    if schema_issues:
        return [issue.message for issue in schema_issues]

    failures: list[str] = []

    def walk(current_schema: dict[str, Any], current_value: Any, path: str) -> None:
        schema_type = current_schema["type"]
        if not _json_type_matches(schema_type, current_value):
            failures.append(f"{path} must be {schema_type}")
            return
        if "enum" in current_schema and current_value not in current_schema["enum"]:
            failures.append(f"{path} must be one of the declared enum values")
        if schema_type == "object":
            properties = current_schema.get("properties", {})
            for required_key in current_schema.get("required", []):
                if required_key not in current_value:
                    failures.append(f"{path}.{required_key} is required")
            additional = current_schema.get("additionalProperties", True)
            if additional is False:
                unknown = set(current_value).difference(properties)
                for key in sorted(unknown):
                    failures.append(f"{path}.{key} is not permitted")
            for key, value in current_value.items():
                property_schema = properties.get(key)
                if isinstance(property_schema, dict):
                    walk(property_schema, value, f"{path}.{key}")
        elif schema_type == "array":
            for index, value in enumerate(current_value):
                walk(current_schema["items"], value, f"{path}[{index}]")

    walk(schema, output, "$")
    return failures


def _node_references(config: dict[str, Any]) -> Iterable[tuple[str, str]]:
    reference_keys = {"input", "inputs", "depends_on", "source_node", "condition_node"}

    def walk(value: Any, key: str | None = None) -> Iterable[tuple[str, str]]:
        if key in reference_keys:
            if isinstance(value, str):
                yield key, value
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        yield key, item
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                yield from walk(child_value, child_key)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item, key)

    yield from walk(config)


def _config_required(issues: list[ValidationIssue], config: dict[str, Any], node_path: str, *keys: str) -> None:
    missing = [key for key in keys if not isinstance(config.get(key), str) or not config[key].strip()]
    if missing:
        _issue(issues, "NODE_CONFIG_REQUIRED", f"{node_path}.config", f"config requires: {', '.join(missing)}")


def _validate_node_config(node: dict[str, Any], issues: list[ValidationIssue]) -> None:
    node_type = node.get("type")
    path = f"nodes[{node.get('key', '?')}]"
    config = node.get("config")
    if not isinstance(config, dict):
        _issue(issues, "NODE_CONFIG_INVALID", f"{path}.config", "config must be an object")
        return
    config_model = NODE_CONFIG_MODELS.get(node_type)
    if config_model is not None:
        try:
            config_model.model_validate(config)
        except ValidationError as exc:
            for error in exc.errors():
                error_path = ".".join(str(part) for part in error.get("loc", ()))
                _issue(
                    issues,
                    "NODE_CONFIG_TYPE_INVALID",
                    f"{path}.config{'.' + error_path if error_path else ''}",
                    str(error.get("msg", "node config has an invalid value")),
                )
    if node_type == "trigger":
        _config_required(issues, config, path, "event")
    elif node_type == "fetch":
        if not any(isinstance(config.get(key), str) and config[key].strip() for key in ("source", "connector_key")):
            _issue(issues, "NODE_CONFIG_REQUIRED", f"{path}.config", "fetch requires source or connector_key")
        _config_required(issues, config, path, "resource")
    elif node_type == "parse":
        _config_required(issues, config, path, "input")
        if not isinstance(config.get("schema"), dict):
            _issue(issues, "NODE_CONFIG_REQUIRED", f"{path}.config.schema", "parse requires a schema object")
    elif node_type == "classify":
        _config_required(issues, config, path, "input")
        if not isinstance(config.get("labels"), list) or not config["labels"]:
            _issue(issues, "NODE_CONFIG_REQUIRED", f"{path}.config.labels", "classify requires a non-empty labels array")
    elif node_type == "extract":
        _config_required(issues, config, path, "input")
        if not isinstance(config.get("fields"), dict) or not config["fields"]:
            _issue(issues, "NODE_CONFIG_REQUIRED", f"{path}.config.fields", "extract requires a non-empty fields object")
    elif node_type == "rule":
        _config_required(issues, config, path, "input", "expression")
    elif node_type == "score":
        _config_required(issues, config, path, "input", "score_key")
    elif node_type == "llm":
        _config_required(issues, config, path, "input", "prompt_key", "model_config_key")
        if "model_id" in config:
            _issue(issues, "MODEL_ID_INLINE_FORBIDDEN", f"{path}.config.model_id", "llm nodes must reference a model config")
        if "output_schema" not in config:
            _issue(issues, "OUTPUT_SCHEMA_REQUIRED", f"{path}.config.output_schema", "llm nodes require a structured output schema")
        else:
            schema_issues: list[ValidationIssue] = []
            _validate_json_schema(config.get("output_schema"), f"{path}.config.output_schema", schema_issues)
            issues.extend(schema_issues)
    elif node_type == "tool":
        _config_required(issues, config, path, "input")
        if not any(isinstance(config.get(key), str) and config[key].strip() for key in ("tool_key", "tool_name")):
            _issue(issues, "NODE_CONFIG_REQUIRED", f"{path}.config", "tool requires tool_key or tool_name")
        if config.get("write") is True and not config.get("requires_approval", False):
            _issue(
                issues,
                "TOOL_WRITE_APPROVAL_REQUIRED",
                f"{path}.config.requires_approval",
                "write-capable tool nodes must declare requires_approval=true",
            )
    elif node_type == "approve":
        _config_required(issues, config, path, "input", "reason")
    elif node_type == "notify":
        _config_required(issues, config, path, "input", "channel")
        if not any(isinstance(config.get(key), str) and config[key].strip() for key in ("recipient", "template")):
            _issue(issues, "NODE_CONFIG_REQUIRED", f"{path}.config", "notify requires recipient or template")
    elif node_type == "halt":
        _config_required(issues, config, path, "input", "reason")


def _validate_external_references(
    db: Session,
    workspace_id: str,
    spec: dict[str, Any],
    workflow: Workflow | None,
    issues: list[ValidationIssue],
) -> None:
    baseline_id = spec.get("baseline_id")
    if baseline_id:
        baseline = db.scalar(select(Baseline).where(Baseline.id == baseline_id, Baseline.workspace_id == workspace_id))
        if baseline is None:
            _issue(issues, "BASELINE_NOT_FOUND", "baseline_id", "referenced baseline is not visible in this workspace")
        elif baseline.status != "signed":
            _issue(issues, "BASELINE_NOT_SIGNED", "baseline_id", "a workflow may reference only a signed baseline")
        elif workflow and workflow.process_id and baseline.process_id != workflow.process_id:
            _issue(issues, "BASELINE_PROCESS_MISMATCH", "baseline_id", "baseline belongs to a different discovery process")

    for node in spec.get("nodes", []):
        if node.get("type") != "llm" or not isinstance(node.get("config"), dict):
            continue
        config = node["config"]
        prompt_key = config.get("prompt_key")
        model_key = config.get("model_config_key")
        prompt = db.scalar(select(Prompt).where(Prompt.workspace_id == workspace_id, Prompt.key == prompt_key))
        if prompt is None:
            _issue(issues, "PROMPT_NOT_FOUND", f"nodes[{node['key']}].config.prompt_key", f"prompt {prompt_key!r} was not found")
        else:
            prompt_version = config.get("prompt_version")
            prompt_query = select(PromptVersion).where(
                PromptVersion.prompt_id == prompt.id,
                PromptVersion.workspace_id == workspace_id,
            )
            if isinstance(prompt_version, int):
                prompt_query = prompt_query.where(PromptVersion.version == prompt_version)
            prompt_query = prompt_query.order_by(PromptVersion.version.desc())
            if db.scalar(prompt_query) is None:
                _issue(
                    issues,
                    "PROMPT_VERSION_NOT_FOUND",
                    f"nodes[{node['key']}].config.prompt_version",
                    f"no version exists for prompt {prompt_key!r}",
                )
        model_query = select(ModelConfig).where(ModelConfig.workspace_id == workspace_id, ModelConfig.key == model_key)
        model_version = config.get("model_config_version")
        if isinstance(model_version, int):
            model_query = model_query.where(ModelConfig.version == model_version)
        model_query = model_query.order_by(ModelConfig.version.desc())
        if db.scalar(model_query) is None:
            _issue(issues, "MODEL_CONFIG_NOT_FOUND", f"nodes[{node['key']}].config.model_config_key", f"model config {model_key!r} was not found")


def validate_workflow_spec(
    payload: WorkflowSpecInput | dict[str, Any],
    *,
    db: Session | None = None,
    workspace_id: str | None = None,
    workflow: Workflow | None = None,
) -> WorkflowValidation:
    spec = migrate_workflow_spec(payload)
    issues: list[ValidationIssue] = []
    nodes = spec["nodes"]
    edges = spec["edges"]
    thresholds = spec["thresholds"]

    node_by_key: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        key = node.get("key")
        path = f"nodes[{index}]"
        if not isinstance(key, str) or not NODE_KEY_PATTERN.fullmatch(key):
            _issue(issues, "NODE_KEY_INVALID", f"{path}.key", "node keys must match ^[a-z][a-z0-9_.-]{0,63}$")
        elif key in node_by_key:
            _issue(issues, "NODE_KEY_DUPLICATE", f"{path}.key", f"node key {key!r} is duplicated")
        else:
            node_by_key[key] = node
        node_type = node.get("type")
        if node_type not in WORKFLOW_NODE_TYPES:
            _issue(issues, "NODE_TYPE_UNSUPPORTED", f"{path}.type", f"node type {node_type!r} is not supported")
        if not isinstance(node.get("label"), str) or not node["label"].strip():
            _issue(issues, "NODE_LABEL_REQUIRED", f"{path}.label", "node label is required")
        _validate_node_config(node, issues)
        for reference_key, reference in _node_references(node.get("config", {})):
            if reference not in node_by_key and reference not in {candidate.get("key") for candidate in nodes}:
                _issue(
                    issues,
                    "NODE_REFERENCE_MISSING",
                    f"{path}.config.{reference_key}",
                    f"referenced node {reference!r} does not exist",
                )

    if not nodes:
        _issue(issues, "TRIGGER_REQUIRED", "nodes", "a publishable workflow requires at least one trigger node")
    triggers = [node for node in nodes if node.get("type") == "trigger"]
    if len(triggers) == 0 and nodes:
        _issue(issues, "TRIGGER_REQUIRED", "nodes", "a publishable workflow requires exactly one trigger node")
    elif len(triggers) > 1:
        _issue(issues, "TRIGGER_MULTIPLE", "nodes", "a workflow may have only one trigger node")

    adjacency: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, int] = {key: 0 for key in node_by_key}
    seen_edges: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        path = f"edges[{index}]"
        source = edge.get("from_node")
        target = edge.get("to_node")
        if source not in node_by_key:
            _issue(issues, "EDGE_SOURCE_MISSING", f"{path}.from_node", f"node {source!r} does not exist")
        if target not in node_by_key:
            _issue(issues, "EDGE_TARGET_MISSING", f"{path}.to_node", f"node {target!r} does not exist")
        if source == target:
            _issue(issues, "DAG_SELF_CYCLE", path, "a node cannot point to itself")
        pair = (source, target)
        if pair in seen_edges:
            _issue(issues, "EDGE_DUPLICATE", path, "duplicate edges are not allowed")
        seen_edges.add(pair)
        if source in node_by_key and target in node_by_key and source != target:
            adjacency[source].append(target)
            incoming[target] += 1

    queue = deque(sorted(key for key, degree in incoming.items() if degree == 0))
    topological: list[str] = []
    mutable_incoming = dict(incoming)
    while queue:
        current = queue.popleft()
        topological.append(current)
        for target in sorted(adjacency.get(current, [])):
            mutable_incoming[target] -= 1
            if mutable_incoming[target] == 0:
                queue.append(target)
    if len(topological) != len(node_by_key):
        _issue(issues, "DAG_CYCLE", "edges", "workflow graph contains a forbidden cycle")

    if triggers:
        trigger_key = triggers[0].get("key")
        if trigger_key in incoming and incoming[trigger_key] > 0:
            _issue(issues, "TRIGGER_HAS_INCOMING_EDGE", f"nodes[{trigger_key}]", "the trigger must be a graph root")
        reachable: set[str] = set()
        if trigger_key in node_by_key:
            walk = deque([trigger_key])
            while walk:
                current = walk.popleft()
                if current in reachable:
                    continue
                reachable.add(current)
                walk.extend(adjacency.get(current, []))
            for key in sorted(set(node_by_key).difference(reachable)):
                _issue(issues, "NODE_UNREACHABLE", f"nodes[{key}]", "node is not reachable from the trigger")

    terminal_types = {"approve", "notify", "halt"}
    if nodes and not any(node.get("type") in terminal_types for node in nodes):
        _issue(issues, "TERMINAL_REQUIRED", "nodes", "a publishable workflow requires an approve, notify, or halt node")

    threshold_keys: set[str] = set()
    for index, threshold in enumerate(thresholds):
        key = threshold.get("key")
        value = threshold.get("value")
        if not isinstance(key, str) or not key.strip():
            _issue(issues, "THRESHOLD_KEY_REQUIRED", f"thresholds[{index}].key", "threshold key is required")
        elif key in threshold_keys:
            _issue(issues, "THRESHOLD_DUPLICATE", f"thresholds[{index}].key", f"threshold {key!r} is duplicated")
        threshold_keys.add(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            _issue(issues, "THRESHOLD_VALUE_INVALID", f"thresholds[{index}].value", "threshold value must be finite numeric data")

    if db is not None and workspace_id is not None:
        _validate_external_references(db, workspace_id, spec, workflow, issues)

    return WorkflowValidation(
        normalized_spec=spec,
        definition_hash=canonical_hash(spec),
        issues=tuple(issues),
    )


def _topological_positions(spec: dict[str, Any]) -> dict[str, dict[str, float]]:
    keys = [node["key"] for node in spec.get("nodes", [])]
    adjacency: dict[str, list[str]] = defaultdict(list)
    incoming = {key: 0 for key in keys}
    for edge in spec.get("edges", []):
        source = edge.get("from_node")
        target = edge.get("to_node")
        if source in incoming and target in incoming and source != target:
            adjacency[source].append(target)
            incoming[target] += 1
    queue = deque(sorted(key for key, degree in incoming.items() if degree == 0))
    levels = {key: 0 for key in keys}
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for target in sorted(adjacency.get(current, [])):
            levels[target] = max(levels[target], levels[current] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    order.extend(key for key in sorted(keys) if key not in order)
    rows_by_level: dict[int, int] = defaultdict(int)
    positions: dict[str, dict[str, float]] = {}
    for key in order:
        level = levels.get(key, 0)
        row = rows_by_level[level]
        positions[key] = {"x": float(level * 280), "y": float(row * 160)}
        rows_by_level[level] += 1
    return positions


def _insert_graph_rows(db: Session, version: WorkflowVersion, spec: dict[str, Any]) -> None:
    positions = _topological_positions(spec)
    for sort_order, node in enumerate(spec["nodes"]):
        db.add(
            WorkflowNode(
                id=new_id(),
                workspace_id=version.workspace_id,
                workflow_version_id=version.id,
                node_key=node["key"],
                node_type=node["type"],
                label=node["label"],
                config_json=node["config"],
                position_json=positions.get(node["key"], {"x": 0.0, "y": float(sort_order * 160)}),
                sort_order=sort_order,
            )
        )
    for edge in spec["edges"]:
        db.add(
            WorkflowEdge(
                id=new_id(),
                workspace_id=version.workspace_id,
                workflow_version_id=version.id,
                from_node=edge["from_node"],
                to_node=edge["to_node"],
                condition_json=edge.get("condition"),
            )
        )
    for threshold in spec["thresholds"]:
        if threshold.get("value") is None:
            continue
        db.add(
            WorkflowThreshold(
                id=new_id(),
                workspace_id=version.workspace_id,
                workflow_version_id=version.id,
                key=threshold["key"],
                value=float(threshold["value"]),
                description=threshold.get("description"),
            )
        )


def _workflow_spec_from_create(payload: WorkflowCreate) -> dict[str, Any]:
    return WorkflowSpecInput(
        nodes=payload.nodes,
        edges=payload.edges,
        thresholds=payload.thresholds,
        prompts=payload.prompts,
        model_configs=payload.model_configs,
        baseline_id=payload.baseline_id,
    ).model_dump(mode="json")


def _workflow_key(payload: WorkflowCreate) -> str:
    if payload.key:
        return payload.key
    derived = re.sub(r"[^a-z0-9]+", "-", payload.name.casefold()).strip("-")
    return (derived or "workflow")[:120]


def create_workflow(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    payload: WorkflowCreate,
) -> tuple[Workflow, WorkflowVersion, WorkflowValidation]:
    process = None
    if payload.process_id:
        process = db.scalar(select(Process).where(Process.id == payload.process_id, Process.workspace_id == workspace_id))
        if process is None:
            raise DomainError("PROCESS_NOT_FOUND", "The workflow process is not visible in this workspace", 404)
    spec = _workflow_spec_from_create(payload)
    workflow = Workflow(
        id=new_id(),
        workspace_id=workspace_id,
        process_id=process.id if process else None,
        key=_workflow_key(payload),
        name=payload.name,
        description=payload.description,
        status="draft",
        created_by=actor_id,
    )
    db.add(workflow)
    db.flush()
    validation = validate_workflow_spec(spec, db=db, workspace_id=workspace_id, workflow=workflow)
    version = WorkflowVersion(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_id=workflow.id,
        version=1,
        schema_version=validation.normalized_spec["schema_version"],
        status="draft",
        spec_json=validation.normalized_spec,
        definition_hash=validation.definition_hash,
        baseline_id=validation.normalized_spec.get("baseline_id"),
        created_by=actor_id,
    )
    db.add(version)
    db.flush()
    _insert_graph_rows(db, version, validation.normalized_spec)
    return workflow, version, validation


def create_workflow_version(
    db: Session,
    *,
    workflow: Workflow,
    workspace_id: str,
    actor_id: str,
    payload: WorkflowVersionCreate,
) -> tuple[WorkflowVersion, WorkflowValidation]:
    if payload.source_version_id is not None:
        source = db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.id == payload.source_version_id,
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.workspace_id == workspace_id,
            )
        )
        if source is None:
            raise DomainError("WORKFLOW_VERSION_NOT_FOUND", "The source workflow version was not found", 404)
    elif payload.source_version is not None:
        source = db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.workspace_id == workspace_id,
                WorkflowVersion.version == payload.source_version,
            )
        )
        if source is None:
            raise DomainError("WORKFLOW_VERSION_NOT_FOUND", "The source workflow version was not found", 404)
    else:
        source = db.scalar(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.workspace_id == workspace_id)
            .order_by(WorkflowVersion.version.desc())
            .limit(1)
        )

    source_spec = dict(source.spec_json) if source is not None else WorkflowSpecInput().model_dump(mode="json")
    fields = payload.model_fields_set
    if "baseline_id" in fields:
        source_spec["baseline_id"] = payload.baseline_id
    if payload.nodes is not None:
        source_spec["nodes"] = [_model_dump(node) for node in payload.nodes]
    if payload.edges is not None:
        source_spec["edges"] = [_model_dump(edge) for edge in payload.edges]
    if payload.thresholds is not None:
        source_spec["thresholds"] = [_model_dump(threshold) for threshold in payload.thresholds]
    if payload.prompts is not None:
        source_spec["prompts"] = payload.prompts
    if payload.model_configs is not None:
        source_spec["model_configs"] = payload.model_configs
    validation = validate_workflow_spec(source_spec, db=db, workspace_id=workspace_id, workflow=workflow)
    next_version = (db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow.id)) or 0) + 1
    version = WorkflowVersion(
        id=new_id(),
        workspace_id=workspace_id,
        workflow_id=workflow.id,
        version=next_version,
        schema_version=validation.normalized_spec["schema_version"],
        status="draft",
        spec_json=validation.normalized_spec,
        definition_hash=validation.definition_hash,
        baseline_id=validation.normalized_spec.get("baseline_id"),
        created_by=actor_id,
    )
    db.add(version)
    db.flush()
    _insert_graph_rows(db, version, validation.normalized_spec)
    return version, validation


def update_workflow_version(
    db: Session,
    *,
    version: WorkflowVersion,
    workflow: Workflow,
    workspace_id: str,
    payload: WorkflowVersionPatch,
) -> WorkflowValidation:
    if version.status != "draft":
        raise DomainError(
            "WORKFLOW_VERSION_IMMUTABLE",
            "Published workflow versions cannot be edited; create a new draft version",
            409,
        )
    spec = dict(version.spec_json or {})
    fields = payload.model_fields_set
    if "schema_version" in fields:
        spec["schema_version"] = payload.schema_version
    if "baseline_id" in fields:
        spec["baseline_id"] = payload.baseline_id
    if "nodes" in fields:
        spec["nodes"] = [_model_dump(node) for node in (payload.nodes or [])]
    if "edges" in fields:
        spec["edges"] = [_model_dump(edge) for edge in (payload.edges or [])]
    if "thresholds" in fields:
        spec["thresholds"] = [_model_dump(threshold) for threshold in (payload.thresholds or [])]
    if "prompts" in fields:
        spec["prompts"] = payload.prompts or []
    if "model_configs" in fields:
        spec["model_configs"] = payload.model_configs or []
    if "metadata" in fields:
        spec["metadata"] = payload.metadata or {}
    validation = validate_workflow_spec(spec, db=db, workspace_id=workspace_id, workflow=workflow)
    version.schema_version = validation.normalized_spec["schema_version"]
    version.spec_json = validation.normalized_spec
    version.definition_hash = validation.definition_hash
    version.baseline_id = validation.normalized_spec.get("baseline_id")
    db.execute(delete(WorkflowNode).where(WorkflowNode.workflow_version_id == version.id))
    db.execute(delete(WorkflowEdge).where(WorkflowEdge.workflow_version_id == version.id))
    db.execute(delete(WorkflowThreshold).where(WorkflowThreshold.workflow_version_id == version.id))
    _insert_graph_rows(db, version, validation.normalized_spec)
    return validation


def get_workflow_or_404(db: Session, workflow_id: str, workspace_id: str) -> Workflow:
    workflow = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id))
    if workflow is None:
        context = db.info.get("request_context")
        if context is not None:
            append_audit_log(
                db,
                action="data.access_denied",
                target_type="workflow",
                target_id=workflow_id,
                workspace_id=workspace_id,
                actor_id=context.user_id,
                after={"reason": "not_visible_in_active_workspace"},
            )
            db.commit()
        raise DomainError("WORKFLOW_NOT_FOUND", f"Workflow {workflow_id} was not found", 404)
    return workflow


def get_workflow_version_or_404(
    db: Session,
    workflow_id: str,
    version_number: int,
    workspace_id: str,
) -> WorkflowVersion:
    version = db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version == version_number,
            WorkflowVersion.workspace_id == workspace_id,
        )
    )
    if version is None:
        raise DomainError("WORKFLOW_VERSION_NOT_FOUND", f"Workflow version {version_number} was not found", 404)
    return version


def _evaluation_gate(db: Session, version: WorkflowVersion) -> tuple[bool, list[str], WorkflowEvaluationResult | None]:
    evaluation = db.scalar(
        select(WorkflowEvaluationResult)
        .where(
            WorkflowEvaluationResult.workflow_version_id == version.id,
            WorkflowEvaluationResult.workspace_id == version.workspace_id,
            WorkflowEvaluationResult.definition_hash == version.definition_hash,
        )
        .order_by(WorkflowEvaluationResult.evaluated_at.desc(), WorkflowEvaluationResult.created_at.desc())
        .limit(1)
    )
    if evaluation is None:
        return False, ["No evaluation result is recorded for the current workflow definition hash"], None
    if not evaluation.passed:
        reasons = [str(reason) for reason in (evaluation.failure_reasons_json or [])]
        return False, reasons or ["The latest evaluation result did not pass"], evaluation
    return True, [], evaluation


def evaluation_gate_payload(db: Session, version: WorkflowVersion) -> dict[str, Any]:
    passing, failure_reasons, evaluation = _evaluation_gate(db, version)
    return {
        "status": "passed" if passing else "blocked",
        "passed": passing,
        "failure_reasons": failure_reasons,
        "evaluation_id": evaluation.id if evaluation else None,
        "evaluated_hash": evaluation.definition_hash if evaluation else None,
        "evaluated_at": evaluation.evaluated_at.isoformat() if evaluation else None,
    }


def validate_version(
    db: Session,
    *,
    version: WorkflowVersion,
    workflow: Workflow,
) -> WorkflowValidation:
    return validate_workflow_spec(
        version.spec_json,
        db=db,
        workspace_id=version.workspace_id,
        workflow=workflow,
    )


def record_evaluation(
    db: Session,
    *,
    version: WorkflowVersion,
    workflow: Workflow,
    actor_id: str,
    payload: WorkflowEvaluationCreate,
) -> WorkflowEvaluationResult:
    if payload.definition_hash != version.definition_hash:
        raise DomainError(
            "EVALUATION_HASH_MISMATCH",
            "Evaluation results must reference the current workflow definition hash",
            409,
            details={"expected_hash": version.definition_hash, "received_hash": payload.definition_hash},
        )
    if payload.passed:
        validation = validate_version(db, version=version, workflow=workflow)
        if not validation.valid:
            raise DomainError(
                "EVALUATION_VERSION_INVALID",
                "A passing evaluation cannot be recorded for an invalid workflow graph",
                422,
                details={"issues": [issue.as_dict() for issue in validation.issues]},
            )
    result = WorkflowEvaluationResult(
        id=new_id(),
        workspace_id=version.workspace_id,
        workflow_version_id=version.id,
        definition_hash=payload.definition_hash,
        passed=payload.passed,
        metrics_json=payload.metrics,
        failure_reasons_json=payload.failure_reasons,
        evaluator=payload.evaluator,
        created_by=actor_id,
        evaluated_at=utc_now(),
    )
    db.add(result)
    db.flush()
    append_audit_log(
        db,
        action="workflow.evaluation.recorded",
        target_type="workflow_version",
        target_id=version.id,
        workspace_id=version.workspace_id,
        actor_id=actor_id,
        after={
            "evaluation_id": result.id,
            "definition_hash": result.definition_hash,
            "passed": result.passed,
            "failure_reasons": result.failure_reasons_json,
        },
    )
    return result


def run_server_evaluation(
    db: Session,
    *,
    version: WorkflowVersion,
    workflow: Workflow,
    actor_id: str,
    suite_key: str,
) -> WorkflowEvaluationResult:
    """Run the bounded server-owned W-01 synthetic gate.

    Callers select a tracked suite; they cannot submit the result, metrics, or
    hash. The result is always bound to the definition currently stored on the
    version, so publish cannot be forged by the browser.
    """

    if suite_key not in {"w01.synthetic.regression", "w01.synthetic.baseline"}:
        raise DomainError("EVALUATION_SUITE_NOT_FOUND", "The requested evaluation suite is not available", 422)

    validation = validate_version(db, version=version, workflow=workflow)
    failure_reasons = [issue.message for issue in validation.issues if issue.severity == "error"]
    passed = validation.valid and suite_key == "w01.synthetic.baseline"
    if suite_key == "w01.synthetic.regression":
        failure_reasons = ["Synthetic regression suite contains a known false-auto case"] + failure_reasons
    metrics = {
        "suite_key": suite_key,
        "schema_valid": validation.valid,
        "false_auto_rate": 0.08 if not passed else 0.01,
    }
    result = WorkflowEvaluationResult(
        id=new_id(),
        workspace_id=version.workspace_id,
        workflow_version_id=version.id,
        definition_hash=version.definition_hash,
        passed=passed,
        metrics_json=metrics,
        failure_reasons_json=failure_reasons,
        evaluator="server.synthetic",
        created_by=actor_id,
        evaluated_at=utc_now(),
    )
    db.add(result)
    db.flush()
    append_audit_log(
        db,
        action="workflow.evaluation_completed",
        target_type="workflow_version",
        target_id=version.id,
        workspace_id=version.workspace_id,
        actor_id=actor_id,
        after={
            "evaluation_id": result.id,
            "suite_key": suite_key,
            "definition_hash": result.definition_hash,
            "passed": result.passed,
            "failure_reasons": result.failure_reasons_json,
        },
    )
    return result


def publish_version(
    db: Session,
    *,
    version: WorkflowVersion,
    workflow: Workflow,
    actor_id: str,
) -> WorkflowEvaluationResult:
    if version.status != "draft":
        raise DomainError(
            "WORKFLOW_VERSION_IMMUTABLE",
            "Only a draft workflow version can be published",
            409,
        )
    validation = validate_version(db, version=version, workflow=workflow)
    if not validation.valid:
        raise DomainError(
            "WORKFLOW_VALIDATION_FAILED",
            "The workflow definition is not publishable",
            422,
            details={"issues": [issue.as_dict() for issue in validation.issues]},
        )
    if validation.definition_hash != version.definition_hash:
        raise DomainError(
            "WORKFLOW_HASH_DRIFT",
            "The stored workflow hash does not match its canonical definition",
            409,
        )
    passing, failure_reasons, evaluation = _evaluation_gate(db, version)
    if not passing or evaluation is None:
        code = "EVALUATION_FAILED" if evaluation is not None else "EVALUATION_REQUIRED"
        message = "The workflow cannot be published until its evaluation gate passes"
        raise DomainError(
            code,
            message,
            409,
            details={
                "definition_hash": version.definition_hash,
                "failure_reasons": failure_reasons,
                "evaluation_id": evaluation.id if evaluation else None,
            },
        )

    version.status = "published"
    version.immutable_hash = version.definition_hash
    version.eval_run_id = evaluation.id
    version.published_at = utc_now()
    version.published_by = actor_id
    workflow.status = "published"
    db.flush()
    append_audit_log(
        db,
        action="workflow.version.published",
        target_type="workflow_version",
        target_id=version.id,
        workspace_id=version.workspace_id,
        actor_id=actor_id,
        after={
            "workflow_id": workflow.id,
            "version": version.version,
            "immutable_hash": version.immutable_hash,
            "evaluation_id": evaluation.id,
            "baseline_id": version.baseline_id,
        },
    )
    return evaluation


def _node_payload(node: WorkflowNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "key": node.node_key,
        "type": node.node_type,
        "label": node.label,
        "config": node.config_json,
        "position": node.position_json,
        "read_only": False,
    }


def graph_payload(db: Session, version: WorkflowVersion) -> dict[str, Any]:
    nodes = db.scalars(
        select(WorkflowNode)
        .where(
            WorkflowNode.workflow_version_id == version.id,
            WorkflowNode.workspace_id == version.workspace_id,
        )
        .order_by(WorkflowNode.sort_order, WorkflowNode.node_key)
    ).all()
    edges = db.scalars(
        select(WorkflowEdge)
        .where(
            WorkflowEdge.workflow_version_id == version.id,
            WorkflowEdge.workspace_id == version.workspace_id,
        )
        .order_by(WorkflowEdge.from_node, WorkflowEdge.to_node)
    ).all()
    return {
        "version_id": version.id,
        "version": version.version,
        "read_only": True,
        "nodes": [
            {
                "id": node.node_key,
                "type": node.node_type,
                "position": node.position_json,
                "data": {"key": node.node_key, "label": node.label, "config": node.config_json},
                "read_only": True,
            }
            for node in nodes
        ],
        "edges": [
            {
                "id": edge.id,
                "source": edge.from_node,
                "target": edge.to_node,
                "data": {"condition": edge.condition_json},
                "read_only": True,
            }
            for edge in edges
        ],
    }


def version_payload(db: Session, version: WorkflowVersion, *, include_graph: bool = True) -> dict[str, Any]:
    nodes = db.scalars(
        select(WorkflowNode)
        .where(WorkflowNode.workflow_version_id == version.id, WorkflowNode.workspace_id == version.workspace_id)
        .order_by(WorkflowNode.sort_order, WorkflowNode.node_key)
    ).all()
    edges = db.scalars(
        select(WorkflowEdge)
        .where(WorkflowEdge.workflow_version_id == version.id, WorkflowEdge.workspace_id == version.workspace_id)
        .order_by(WorkflowEdge.from_node, WorkflowEdge.to_node)
    ).all()
    thresholds = db.scalars(
        select(WorkflowThreshold)
        .where(WorkflowThreshold.workflow_version_id == version.id, WorkflowThreshold.workspace_id == version.workspace_id)
        .order_by(WorkflowThreshold.key)
    ).all()
    payload: dict[str, Any] = {
        "id": version.id,
        "workflow_id": version.workflow_id,
        "workspace_id": version.workspace_id,
        "version": version.version,
        "schema_version": version.schema_version,
        "status": version.status,
        "spec": version.spec_json,
        "definition_hash": version.definition_hash,
        "immutable_hash": version.immutable_hash,
        "baseline_id": version.baseline_id,
        "eval_run_id": version.eval_run_id,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "published_by": version.published_by,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat(),
        "updated_at": version.updated_at.isoformat(),
        "nodes": [_node_payload(node) for node in nodes],
        "edges": [
            {
                "id": edge.id,
                "from_node": edge.from_node,
                "to_node": edge.to_node,
                "condition": edge.condition_json,
            }
            for edge in edges
        ],
        "thresholds": [
            {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}
            for threshold in thresholds
        ],
        "evaluation_gate": evaluation_gate_payload(db, version),
    }
    if include_graph:
        payload["graph"] = graph_payload(db, version)
    return payload


def workflow_payload(db: Session, workflow: Workflow) -> dict[str, Any]:
    latest = db.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.workspace_id == workflow.workspace_id)
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )
    published = db.scalar(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.workflow_id == workflow.id,
            WorkflowVersion.workspace_id == workflow.workspace_id,
            WorkflowVersion.status == "published",
        )
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )
    return {
        "id": workflow.id,
        "workspace_id": workflow.workspace_id,
        "process_id": workflow.process_id,
        "key": workflow.key,
        "name": workflow.name,
        "description": workflow.description,
        "status": workflow.status,
        "latest_version": latest.version if latest else None,
        "latest_version_id": latest.id if latest else None,
        "published_version": published.version if published else None,
        "published_version_id": published.id if published else None,
        "created_by": workflow.created_by,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
    }


def evaluation_payload(result: WorkflowEvaluationResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "workflow_version_id": result.workflow_version_id,
        "definition_hash": result.definition_hash,
        "passed": result.passed,
        "metrics": result.metrics_json,
        "failure_reasons": result.failure_reasons_json,
        "evaluator": result.evaluator,
        "created_by": result.created_by,
        "evaluated_at": result.evaluated_at.isoformat(),
    }


def _prompt_version_payload(version: PromptVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "prompt_id": version.prompt_id,
        "workspace_id": version.workspace_id,
        "version": version.version,
        "body": version.body,
        "variables": version.variables_json,
        "output_schema": version.output_schema_json,
        "canonical_hash": version.canonical_hash,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat(),
    }


def prompt_payload(db: Session, prompt: Prompt) -> dict[str, Any]:
    versions = db.scalars(
        select(PromptVersion)
        .where(PromptVersion.prompt_id == prompt.id, PromptVersion.workspace_id == prompt.workspace_id)
        .order_by(PromptVersion.version.desc())
    ).all()
    return {
        "id": prompt.id,
        "workspace_id": prompt.workspace_id,
        "key": prompt.key,
        "description": prompt.description,
        "versions": [_prompt_version_payload(version) for version in versions],
        "created_by": prompt.created_by,
        "created_at": prompt.created_at.isoformat(),
        "updated_at": prompt.updated_at.isoformat(),
    }


def _validate_prompt_output_schema(output_schema: dict[str, Any] | None) -> None:
    if output_schema is None:
        return
    issues: list[ValidationIssue] = []
    _validate_json_schema(output_schema, "$", issues)
    if issues:
        raise DomainError(
            "OUTPUT_SCHEMA_INVALID",
            "The prompt output schema is invalid",
            422,
            details={"issues": [issue.as_dict() for issue in issues]},
        )


def create_prompt(db: Session, *, workspace_id: str, actor_id: str, payload: PromptCreate) -> Prompt:
    existing = db.scalar(select(Prompt).where(Prompt.workspace_id == workspace_id, Prompt.key == payload.key))
    if existing is not None:
        raise DomainError("PROMPT_ALREADY_EXISTS", "A prompt with this key already exists", 409)
    _validate_prompt_output_schema(payload.output_schema)
    prompt = Prompt(
        id=new_id(), workspace_id=workspace_id, key=payload.key, description=payload.description, created_by=actor_id
    )
    db.add(prompt)
    db.flush()
    version_payload = {
        "body": payload.body,
        "variables": payload.variables,
        "output_schema": payload.output_schema,
    }
    db.add(
        PromptVersion(
            id=new_id(),
            workspace_id=workspace_id,
            prompt_id=prompt.id,
            version=1,
            body=payload.body,
            variables_json=payload.variables,
            output_schema_json=payload.output_schema,
            canonical_hash=canonical_hash(version_payload),
            created_by=actor_id,
        )
    )
    return prompt


def create_prompt_version(
    db: Session,
    *,
    prompt: Prompt,
    actor_id: str,
    payload: PromptVersionCreate,
) -> PromptVersion:
    _validate_prompt_output_schema(payload.output_schema)
    next_version = (db.scalar(select(func.max(PromptVersion.version)).where(PromptVersion.prompt_id == prompt.id)) or 0) + 1
    version_payload = {
        "body": payload.body,
        "variables": payload.variables,
        "output_schema": payload.output_schema,
    }
    version = PromptVersion(
        id=new_id(),
        workspace_id=prompt.workspace_id,
        prompt_id=prompt.id,
        version=next_version,
        body=payload.body,
        variables_json=payload.variables,
        output_schema_json=payload.output_schema,
        canonical_hash=canonical_hash(version_payload),
        created_by=actor_id,
    )
    db.add(version)
    return version


def _assert_no_secret_params(params: dict[str, Any]) -> None:
    leaked: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in SECRET_PARAM_KEYS:
                    leaked.add(str(key))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(params)
    if leaked:
        raise DomainError(
            "MODEL_CONFIG_SECRET_FORBIDDEN",
            "Model config params cannot contain credential or secret values",
            422,
            details={"forbidden_keys": sorted(leaked)},
        )


def create_model_config(db: Session, *, workspace_id: str, actor_id: str, payload: ModelConfigCreate) -> ModelConfig:
    _assert_no_secret_params(payload.params)
    requested_version = payload.version
    if requested_version is None:
        requested_version = (
            db.scalar(
                select(func.max(ModelConfig.version)).where(
                    ModelConfig.workspace_id == workspace_id,
                    ModelConfig.key == payload.key,
                )
            )
            or 0
        ) + 1
    duplicate = db.scalar(
        select(ModelConfig).where(
            ModelConfig.workspace_id == workspace_id,
            ModelConfig.key == payload.key,
            ModelConfig.version == requested_version,
        )
    )
    if duplicate is not None:
        raise DomainError("MODEL_CONFIG_ALREADY_EXISTS", "This model config version already exists", 409)
    config = ModelConfig(
        id=new_id(),
        workspace_id=workspace_id,
        key=payload.key,
        version=requested_version,
        provider=payload.provider,
        model_id=payload.model_id,
        params_json=payload.params,
        created_by=actor_id,
    )
    db.add(config)
    return config


def model_config_payload(config: ModelConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "workspace_id": config.workspace_id,
        "key": config.key,
        "version": config.version,
        "provider": config.provider,
        "model_id": config.model_id,
        "params": config.params_json,
        "created_by": config.created_by,
        "created_at": config.created_at.isoformat(),
    }
