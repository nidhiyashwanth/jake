from app.services.workflow import (
    CURRENT_WORKFLOW_SCHEMA_VERSION,
    migrate_workflow_spec,
    validate_structured_output,
    validate_workflow_spec,
)
from app.services.authorization import role_allows


def _valid_spec() -> dict:
    return {
        "schema_version": CURRENT_WORKFLOW_SCHEMA_VERSION,
        "nodes": [
            {"key": "trigger", "type": "trigger", "label": "Document received", "config": {"event": "document.received"}},
            {
                "key": "fetch_doc",
                "type": "fetch",
                "label": "Fetch document",
                "config": {"input": "trigger", "source": "upload", "resource": "document"},
            },
            {
                "key": "parse_doc",
                "type": "parse",
                "label": "Parse document",
                "config": {"input": "fetch_doc", "schema": {"type": "object"}},
            },
            {
                "key": "approve",
                "type": "approve",
                "label": "Human approval",
                "config": {"input": "parse_doc", "reason": "Review extracted compliance fields"},
            },
        ],
        "edges": [
            {"from_node": "trigger", "to_node": "fetch_doc", "condition": None},
            {"from_node": "fetch_doc", "to_node": "parse_doc", "condition": None},
            {"from_node": "parse_doc", "to_node": "approve", "condition": None},
        ],
        "thresholds": [{"key": "theta_review", "value": 0.88, "description": "Route uncertain cases to review"}],
    }


def test_validates_all_supported_node_types_and_returns_a_publishable_contract() -> None:
    spec = _valid_spec()
    spec["nodes"].extend(
        [
            {"key": "classify_doc", "type": "classify", "label": "Classify", "config": {"input": "parse_doc", "labels": ["coi"]}},
            {"key": "extract_fields", "type": "extract", "label": "Extract", "config": {"input": "classify_doc", "fields": {"expiry": {"type": "string"}}}},
            {"key": "rule_check", "type": "rule", "label": "Rule", "config": {"input": "extract_fields", "expression": "expiry >= today"}},
            {"key": "score_case", "type": "score", "label": "Score", "config": {"input": "rule_check", "score_key": "confidence"}},
            {
                "key": "llm_extract",
                "type": "llm",
                "label": "Structured extraction",
                "config": {
                    "input": "score_case",
                    "prompt_key": "coi.extract",
                    "model_config_key": "default.review",
                    "output_schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                        "additionalProperties": False,
                    },
                },
            },
            {"key": "tool_lookup", "type": "tool", "label": "Lookup", "config": {"input": "llm_extract", "tool_key": "vendor.lookup"}},
            {"key": "notify_owner", "type": "notify", "label": "Notify", "config": {"input": "tool_lookup", "channel": "email", "recipient": "owner"}},
            {"key": "halt_case", "type": "halt", "label": "Halt", "config": {"input": "notify_owner", "reason": "Manual intervention required"}},
        ]
    )
    spec["edges"].extend(
        [
            {"from_node": "parse_doc", "to_node": "classify_doc", "condition": None},
            {"from_node": "classify_doc", "to_node": "extract_fields", "condition": None},
            {"from_node": "extract_fields", "to_node": "rule_check", "condition": None},
            {"from_node": "rule_check", "to_node": "score_case", "condition": None},
            {"from_node": "score_case", "to_node": "llm_extract", "condition": None},
            {"from_node": "llm_extract", "to_node": "tool_lookup", "condition": None},
            {"from_node": "tool_lookup", "to_node": "notify_owner", "condition": None},
            {"from_node": "notify_owner", "to_node": "halt_case", "condition": None},
        ]
    )

    result = validate_workflow_spec(spec)

    assert result.valid is True
    assert result.definition_hash == validate_workflow_spec(dict(reversed(list(spec.items())))).definition_hash
    assert result.normalized_spec["schema_version"] == CURRENT_WORKFLOW_SCHEMA_VERSION


def test_cycle_and_missing_node_reference_are_explicit_validation_failures() -> None:
    spec = _valid_spec()
    spec["nodes"][1]["config"]["input"] = "missing_node"
    spec["edges"].append({"from_node": "approve", "to_node": "trigger", "condition": None})

    result = validate_workflow_spec(spec)
    codes = {issue["code"] for issue in result.as_dict()["issues"]}

    assert result.valid is False
    assert "NODE_REFERENCE_MISSING" in codes
    assert "DAG_CYCLE" in codes
    assert "TRIGGER_HAS_INCOMING_EDGE" in codes


def test_llm_output_schema_is_required_and_outputs_are_checked_deterministically() -> None:
    spec = _valid_spec()
    spec["nodes"].append(
        {
            "key": "llm_node",
            "type": "llm",
            "label": "Structured model call",
            "config": {
                "input": "parse_doc",
                "prompt_key": "prompt",
                "model_config_key": "model",
            },
        }
    )
    spec["edges"].append({"from_node": "parse_doc", "to_node": "llm_node", "condition": None})
    invalid = validate_workflow_spec(spec)
    assert any(issue["code"] == "OUTPUT_SCHEMA_REQUIRED" for issue in invalid.as_dict()["issues"])

    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}, "score": {"type": "number"}},
        "required": ["status"],
        "additionalProperties": False,
    }
    assert validate_structured_output(schema, {"status": "review", "score": 0.91}) == []
    assert validate_structured_output(schema, {"score": "high", "extra": True}) == [
        "$.status is required",
        "$.extra is not permitted",
        "$.score must be number",
    ]


def test_legacy_graph_aliases_migrate_to_the_stable_v1_contract() -> None:
    migrated = migrate_workflow_spec(
        {
            "version": 1,
            "nodes": [{"id": "trigger", "type": "trigger", "label": "Receive", "config_json": {"event": "received"}}],
            "edges": [{"from": "trigger", "to": "halt", "condition": None}],
            "thresholds": [],
        }
    )

    assert migrated["schema_version"] == CURRENT_WORKFLOW_SCHEMA_VERSION
    assert migrated["nodes"][0]["key"] == "trigger"
    assert migrated["nodes"][0]["config"] == {"event": "received"}
    assert migrated["edges"][0]["from_node"] == "trigger"


def test_workflow_permissions_keep_builder_publish_and_evaluation_write_separate() -> None:
    assert role_allows("builder", "workflow.create")
    assert role_allows("builder", "workflow.publish")
    assert not role_allows("builder", "workflow.evaluation.write")
    assert role_allows("admin", "workflow.evaluation.write")
    assert role_allows("viewer", "workflow.read")
    assert not role_allows("viewer", "workflow.create")
