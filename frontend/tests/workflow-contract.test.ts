import assert from "node:assert/strict";
import { test } from "node:test";

import type { WorkflowSpec } from "../src/lib/types.ts";
import { emptyWorkflowSpec, normalizeWorkflowVersion, serializeWorkflowSpec, validateWorkflowSpec } from "../src/lib/workflow-contract.ts";

function validSpec(): WorkflowSpec {
  const spec = emptyWorkflowSpec();
  spec.nodes = [
    { id: "start-id", node_key: "start", type: "trigger", label: "Receive document", config: { event: "document.received" } },
    { id: "parse-id", node_key: "parse", type: "parse", label: "Parse document", config: { document_type: "COI" } },
    { id: "rule-id", node_key: "check", type: "rule", label: "Check requirements", config: { expression: "all_requirements_pass" } },
    { id: "halt-id", node_key: "halt", type: "halt", label: "Stop with reason", config: { reason: "Requirement failed" } },
  ];
  spec.edges = [
    { id: "edge-1", from_node: "start", to_node: "parse", condition: null },
    { id: "edge-2", from_node: "parse", to_node: "check", condition: null },
    { id: "edge-3", from_node: "check", to_node: "halt", condition: "failed == true" },
  ];
  spec.thresholds = [
    { key: "theta_review", value: 0.7 },
    { key: "theta_auto", value: 0.9 },
    { key: "value_at_risk_limit", value: 10000 },
  ];
  return spec;
}

test("accepts a connected, thresholded workflow DAG", () => {
  const issues = validateWorkflowSpec(validSpec());
  assert.equal(issues.filter((issue) => issue.severity === "error").length, 0);
});

test("rejects cycles instead of allowing graph control to loop", () => {
  const spec = validSpec();
  spec.edges.push({ id: "cycle", from_node: "check", to_node: "start", condition: "retry" });
  assert.ok(validateWorkflowSpec(spec).some((issue) => issue.code === "cycle_detected"));
});

test("requires schema-constrained model output and registered references", () => {
  const spec = validSpec();
  spec.nodes.splice(2, 1, {
    id: "llm-id",
    node_key: "judge",
    type: "llm",
    label: "Judge exception",
    config: { prompt_key: "missing.prompt", model_config_key: "missing.model", output_schema: "not-json" },
  });
  spec.edges[1] = { id: "edge-2", from_node: "parse", to_node: "judge", condition: null };
  spec.edges[2] = { id: "edge-3", from_node: "judge", to_node: "halt", condition: null };
  const codes = validateWorkflowSpec(spec).map((issue) => issue.code);
  assert.ok(codes.includes("invalid_json_config"));
  assert.ok(codes.includes("prompt_reference_missing"));
  assert.ok(codes.includes("model_config_reference_missing"));
});

test("requires idempotency and compensation for external tool writes", () => {
  const spec = validSpec();
  spec.nodes.splice(2, 1, {
    id: "tool-id",
    node_key: "write",
    type: "tool",
    label: "Write record",
    config: { tool_key: "records.update", writes_external: true },
  });
  spec.edges[1] = { id: "edge-2", from_node: "parse", to_node: "write", condition: null };
  spec.edges[2] = { id: "edge-3", from_node: "write", to_node: "halt", condition: null };
  const codes = validateWorkflowSpec(spec).map((issue) => issue.code);
  assert.ok(codes.includes("idempotency_key_required"));
  assert.ok(codes.includes("compensation_required"));
});

test("serializes only the versioned workflow contract fields", () => {
  const serialized = serializeWorkflowSpec(validSpec());
  assert.equal(serialized.schema_version, "workflow.v1");
  assert.ok(Array.isArray(serialized.nodes));
  assert.ok(Array.isArray(serialized.edges));
  assert.ok(Array.isArray(serialized.thresholds));
  assert.equal(Object.prototype.hasOwnProperty.call(serialized, "immutable_hash"), false);
});

test("normalizes a wrapped API version without dropping its graph", () => {
  const normalized = normalizeWorkflowVersion({ version: { id: "v1", version: 1, status: "draft", spec: validSpec() } }, "workflow-1");
  assert.equal(normalized.id, "v1");
  assert.equal(normalized.spec.nodes.length, 4);
  assert.equal(normalized.workflow_id, "workflow-1");
});
