#!/usr/bin/env python3
"""Validate repository JSON Schemas and their representative instances.

The project intentionally has no runtime dependency on a third-party JSON Schema
package. This tool implements the deterministic Draft 2020-12 subset used by the
repository contracts: types, required, properties, additionalProperties, items,
enum, const, refs, bounds, patterns, formats and unique arrays.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SUPPORTED_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
IGNORED_ANNOTATIONS = {"$schema", "$id", "title", "description", "default", "examples", "$comment"}
SUPPORTED_KEYWORDS = {
    "$schema", "$id", "$ref", "$defs", "title", "description", "default", "examples", "$comment",
    "type", "required", "properties", "additionalProperties", "items", "enum", "const",
    "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "format",
    "minProperties", "maxProperties", "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def type_matches(value: Any, expected: str) -> bool:
    actual = json_type(value)
    return actual == expected or (expected == "number" and actual == "integer")


def resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported external $ref: {ref}")
    current: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        current = current[part]
    return current


def validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:
        return validate(value, resolve_ref(root, schema["$ref"]), root, path)
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum")
    if "if" in schema:
        condition_errors = validate(value, schema["if"], root, path)
        if not condition_errors and "then" in schema:
            errors.extend(validate(value, schema["then"], root, path))
        elif condition_errors and "else" in schema:
            errors.extend(validate(value, schema["else"], root, path))
    if "allOf" in schema:
        for item in schema["allOf"]:
            errors.extend(validate(value, item, root, path))
    if "anyOf" in schema:
        candidates = [validate(value, item, root, path) for item in schema["anyOf"]]
        if candidates and all(candidate for candidate in candidates):
            errors.append(f"{path}: value does not satisfy anyOf")
    if "oneOf" in schema:
        candidates = [validate(value, item, root, path) for item in schema["oneOf"]]
        if sum(1 for candidate in candidates if not candidate) != 1:
            errors.append(f"{path}: value must satisfy exactly one oneOf branch")
    if "not" in schema and not validate(value, schema["not"], root, path):
        errors.append(f"{path}: value matches forbidden not schema")
    if "type" in schema:
        expected = schema["type"]
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(type_matches(value, item) for item in expected_types):
            errors.append(f"{path}: expected type {expected}, got {json_type(value)}")
            return errors
    actual = json_type(value)
    if actual == "object":
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], root, f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: additional property not allowed: {key}")
            elif isinstance(additional, dict):
                errors.extend(validate(item, additional, root, f"{path}.{key}"))
        if len(value) < int(schema.get("minProperties", 0)):
            errors.append(f"{path}: object has fewer than minProperties")
        if "maxProperties" in schema and len(value) > int(schema["maxProperties"]):
            errors.append(f"{path}: object has more than maxProperties")
    elif actual == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(validate(item, items, root, f"{path}[{index}]"))
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(f"{path}: array has fewer than {schema.get('minItems')} items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: array has more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            rendered = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(rendered) != len(set(rendered)):
                errors.append(f"{path}: array items must be unique")
    elif actual == "string":
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path}: string is shorter than minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: string is longer than maxLength")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: string does not match pattern {schema['pattern']}")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path}: invalid date-time")
    elif actual in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value is above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: value is not above exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: value is not below exclusiveMaximum")
    return errors


def schema_definition_errors(schema: dict[str, Any], where: str = "$") -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(schema) - SUPPORTED_KEYWORDS)
    if unknown:
        errors.append(f"{where}: unsupported schema keywords: {unknown}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        invalid = [item for item in types if item not in SUPPORTED_TYPES]
        if invalid:
            errors.append(f"{where}: invalid types: {invalid}")
    for key, value in (schema.get("properties") or {}).items():
        errors.extend(schema_definition_errors(value, f"{where}.properties.{key}"))
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        errors.extend(schema_definition_errors(additional, f"{where}.additionalProperties"))
    if isinstance(schema.get("items"), dict):
        errors.extend(schema_definition_errors(schema["items"], f"{where}.items"))
    for keyword in ("if", "then", "else"):
        if isinstance(schema.get(keyword), dict):
            errors.extend(schema_definition_errors(schema[keyword], f"{where}.{keyword}"))
    for keyword in ("allOf", "anyOf", "oneOf"):
        for index, value in enumerate(schema.get(keyword) or []):
            errors.extend(schema_definition_errors(value, f"{where}.{keyword}[{index}]"))
    if isinstance(schema.get("not"), dict):
        errors.extend(schema_definition_errors(schema["not"], f"{where}.not"))
    for key, value in (schema.get("$defs") or {}).items():
        errors.extend(schema_definition_errors(value, f"{where}.$defs.{key}"))
    return errors


MAPPINGS = {
    "examples/agent-collaboration/agent-task.json": "agent-task.schema.json",
    "examples/agent-collaboration/review-plan.json": "review-plan.schema.json",
    "examples/agent-collaboration/review-result.json": "review-result.schema.json",
    "examples/agent-collaboration/handoff.json": "handoff.schema.json",
    "examples/agent-collaboration/decision-card.json": "decision-card.schema.json",
    "examples/agent-collaboration/escalation.json": "escalation.schema.json",
    "examples/semantic-review/accepted.json": "semantic-consistency-input.schema.json",
    "examples/p05/delivery-quality-baseline.json": "delivery-quality-benchmark.schema.json",
    "examples/delivery-complete/gate-input.json": "delivery-complete-input.schema.json",
    "examples/delivery-complete/quality-benchmark-result.json": "delivery-quality-benchmark-result.schema.json",
    "examples/delivery-complete/semantic-review.json": "review-result.schema.json",
    "examples/delivery-complete/research-record.json": "research-record.schema.json",
    "examples/delivery-complete/artifact-quality.json": "delivery-artifact-quality-result.schema.json",
    "examples/delivery-complete/package-evidence.json": "delivery-package-evidence.schema.json",
    "examples/delivery-complete/artifacts/runtime-evidence.json": "runtime-evidence.schema.json",
    "examples/research/producer-registry.example.json": "producer-registry.schema.json",
    "examples/research/adapter-config.example.json": "research-adapter-config.schema.json",
    "examples/research/research-request.example.json": "research-request.schema.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    schema_dir = root / "schemas" if (root / "schemas").exists() else root / "references"
    failed = 0
    schemas: dict[str, dict[str, Any]] = {}
    non_schema_files = {"approved-ruleset-versions.json", "gate-policy-current.json"}
    for path in sorted(schema_dir.glob("*.json")):
        if path.name in non_schema_files:
            continue
        try:
            data = load(path)
            errors = schema_definition_errors(data)
            if errors:
                failed += 1
                print(f"FAIL {path.name}: " + "; ".join(errors))
            else:
                schemas[path.name] = data
                print(f"OK {path.name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {path.name}: {exc}")
    validated_instances = 0
    for instance_rel, schema_name in MAPPINGS.items():
        instance_path = root / instance_rel
        if not instance_path.exists() or schema_name not in schemas:
            failed += 1
            print(f"FAIL instance {instance_rel}: mapped schema unavailable")
            continue
        errors = validate(load(instance_path), schemas[schema_name], schemas[schema_name])
        validated_instances += 1
        if errors:
            failed += 1
            print(f"FAIL instance {instance_rel}: " + "; ".join(errors[:10]))
        else:
            print(f"OK instance {instance_rel} -> {schema_name}")
    print(json.dumps({"schemas": len(schemas), "instances": validated_instances, "failures": failed}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
