"""Build one example payload per managed-host state from a NICo AsyncAPI spec.

Payloads are derived from the schema (required properties only, first enum
value, first oneOf branch) so no hand-written NICo knowledge is involved.
"""
import copy

import yaml


def load_spec(path):
    with open(path) as f:
        return yaml.safe_load(f)


def resolve(spec, node):
    while isinstance(node, dict) and "$ref" in node:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    return node


def example(spec, node, depth=0):
    if depth > 40:
        raise RuntimeError("schema recursion too deep")
    node = resolve(spec, node)
    if "const" in node:
        return node["const"]
    if "enum" in node:
        return node["enum"][0]
    for key in ("oneOf", "anyOf"):
        if key in node:
            return example(spec, node[key][0], depth + 1)
    if "allOf" in node:
        merged = {}
        for part in node["allOf"]:
            merged.update(example(spec, part, depth + 1))
        return merged
    t = node.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), t[0])
    if t == "object" or "properties" in node:
        out = {}
        props = node.get("properties", {})
        for name in node.get("required", []):
            out[name] = example(spec, props[name], depth + 1)
        return out
    if t == "array":
        return [example(spec, node["items"], depth + 1)] if node.get("items") else []
    if t == "string":
        fmt = node.get("format")
        if fmt == "date-time":
            return "2026-10-19T10:00:00Z"
        if fmt == "uuid":
            return "123e4567-e89b-12d3-a456-426614174000"
        return "example"
    if t == "integer":
        return node.get("minimum", 1)
    if t == "number":
        return node.get("minimum", 1.0)
    if t == "boolean":
        return True
    if t == "null":
        return None
    return {}


def state_name(branch):
    return branch["properties"]["state"]["enum"][0]


def state_branches(spec):
    return spec["components"]["schemas"]["ManagedHostState"]["oneOf"]


def state_list(spec):
    return [state_name(b) for b in state_branches(spec)]


def valid_payloads(spec):
    """One valid message per state, keyed by state name."""
    out = {}
    for branch in state_branches(spec):
        name = state_name(branch)
        out[name] = {
            "machine_id": f"host-{name}",
            "timestamp": "2026-10-19T10:00:00Z",
            "managed_host_state": example(spec, branch),
        }
    return out


def invalid_payloads(valid):
    """Three deliberately broken messages, each derived from the 'ready' payload."""
    missing = copy.deepcopy(valid["ready"])
    del missing["machine_id"]

    unknown_state = copy.deepcopy(valid["ready"])
    unknown_state["machine_id"] = "bad-unknown-state"
    unknown_state["managed_host_state"] = {"state": "not-a-real-state"}

    wrong_type = copy.deepcopy(valid["ready"])
    wrong_type["machine_id"] = "bad-wrong-timestamp-type"
    wrong_type["timestamp"] = 1760868000

    return {
        "bad-missing-machine-id": missing,
        "bad-unknown-state": unknown_state,
        "bad-wrong-timestamp-type": wrong_type,
    }
