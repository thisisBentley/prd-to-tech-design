#!/usr/bin/env python3
"""Deterministic prototype diff, impact, scope and patch helpers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from validate_json_schemas import load as schema_load, validate as schema_validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
CHANGE_ORDER = ["COSMETIC", "STRUCTURAL", "BEHAVIORAL", "DATA_CONTRACT", "PERMISSION", "RUNTIME", "POLICY"]
PRECEDENCE = {name: index for index, name in enumerate(CHANGE_ORDER)}
RERUN_RULES = {
    "COSMETIC": ["STATIC_UI_CHECK"],
    "STRUCTURAL": ["STATIC_UI_CHECK", "VISIBLE_INTERACTION"],
    "BEHAVIORAL": ["INTERACTION_CONTRACT", "RUNTIME_REPLAY", "SEMANTIC_REVIEW"],
    "DATA_CONTRACT": ["DATA_CONTRACT_CHECK", "DOWNSTREAM_REBIND", "SEMANTIC_REVIEW"],
    "PERMISSION": ["PERMISSION_MATRIX", "RUNTIME_REPLAY", "SEMANTIC_REVIEW"],
    "RUNTIME": ["RUNTIME_REPLAY", "INTERACTION_CONTRACT"],
    "POLICY": ["FULL_AUDIT", "SEMANTIC_REVIEW"],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def schema(name: str) -> dict[str, Any]:
    return schema_load(SCHEMA_DIR / name)


def validate_schema_value(value: Any, schema_name: str) -> list[str]:
    document = schema(schema_name)
    return schema_validate(value, document, document)


def sorted_unique(values: Iterable[str]) -> list[str]:
    return sorted({str(value) for value in values if str(value).strip()})


def node_key(node: dict[str, Any]) -> str:
    if node.get("dataAiId"):
        return f"data-ai:{node['dataAiId']}"
    if node.get("id"):
        return f"id:{node['id']}"
    test_id = (node.get("attributes") or {}).get("data-testid")
    if test_id:
        return f"testid:{test_id}"
    return f"dom:{node.get('domPath', '')}"


def ui_element_id(node: dict[str, Any] | None) -> str | None:
    if not node:
        return None
    return node.get("dataAiId") or None


def node_snapshot(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag": node.get("tag"),
        "id": node.get("id"),
        "classes": node.get("classes", []),
        "attributes": node.get("attributes", {}),
        "dataAiId": node.get("dataAiId"),
        "text": node.get("ownText", ""),
        "interactive": node.get("interactive", False),
        "eventAttributes": node.get("eventAttributes", {}),
        "parentNodeId": node.get("parentNodeId"),
        "domPath": node.get("domPath"),
    }


def classify_node_fields(before: dict[str, Any], after: dict[str, Any]) -> tuple[list[str], list[str]]:
    kinds: set[str] = set()
    fields: list[str] = []
    before_snap = node_snapshot(before)
    after_snap = node_snapshot(after)
    for field in sorted(set(before_snap) | set(after_snap)):
        if before_snap.get(field) == after_snap.get(field):
            continue
        fields.append(field)
        if field == "tag":
            kinds.add("STRUCTURAL")
        elif field in {"parentNodeId", "domPath"}:
            kinds.add("STRUCTURAL")
        elif field == "eventAttributes":
            kinds.add("BEHAVIORAL")
        elif field == "interactive":
            kinds.add("BEHAVIORAL")
        elif field in {"classes", "text"}:
            kinds.add("COSMETIC")
        elif field == "dataAiId":
            kinds.add("BEHAVIORAL")
            kinds.add("DATA_CONTRACT")
        elif field == "attributes":
            before_attrs = before_snap.get("attributes") or {}
            after_attrs = after_snap.get("attributes") or {}
            for attr in sorted(set(before_attrs) | set(after_attrs)):
                if before_attrs.get(attr) == after_attrs.get(attr):
                    continue
                lower = attr.lower()
                if lower == "style" or lower in {"class", "title", "aria-label"}:
                    kinds.add("COSMETIC")
                elif lower.startswith("data-ai-"):
                    kinds.add("DATA_CONTRACT")
                elif "permission" in lower or "role" in lower or lower.startswith("aria-"):
                    kinds.add("PERMISSION")
                elif lower.startswith("data-") or "state" in lower or "status" in lower:
                    kinds.add("DATA_CONTRACT")
                    kinds.add("RUNTIME")
                elif lower.startswith("on"):
                    kinds.add("BEHAVIORAL")
                else:
                    kinds.add("STRUCTURAL")
        else:
            kinds.add("STRUCTURAL")
    return sorted(kinds, key=lambda item: PRECEDENCE[item]), fields


def add_change(changes: list[dict[str, Any]], action: str, target_type: str, target_key: str, kinds: list[str], fields: list[str], evidence: list[str], node: dict[str, Any] | None = None, before: Any = None, after: Any = None) -> None:
    kinds = sorted(set(kinds), key=lambda item: PRECEDENCE[item]) or ["COSMETIC"]
    payload = {
        "action": action,
        "targetType": target_type,
        "targetKey": target_key,
        "changeKinds": kinds,
        "fieldsChanged": sorted(set(fields)),
        "evidenceRefs": sorted_unique(evidence),
    }
    if node:
        if node.get("dataAiId"):
            payload["uiElementId"] = node["dataAiId"]
        payload["nodeId"] = node["nodeId"]
        payload["selector"] = node.get("selector")
    if before is not None:
        payload["beforeHash"] = canonical_hash(before)
    if after is not None:
        payload["afterHash"] = canonical_hash(after)
    payload["changeId"] = "CHG-" + canonical_hash(payload)[:12]
    changes.append(payload)


def build_change_set(previous: dict[str, Any], current: dict[str, Any], previous_model_path: Path, current_model_path: Path, workflow_id: str | None = None, from_revision: str | None = None, to_revision: str | None = None) -> dict[str, Any]:
    old_nodes = {node_key(node): node for node in previous.get("nodes", [])}
    new_nodes = {node_key(node): node for node in current.get("nodes", [])}
    changes: list[dict[str, Any]] = []
    counts = {"nodesAdded": 0, "nodesDeleted": 0, "nodesModified": 0, "eventsChanged": 0, "statesChanged": 0, "scriptsChanged": 0}
    evidence = [str(previous_model_path), str(current_model_path)]
    for key in sorted(set(new_nodes) - set(old_nodes)):
        node = new_nodes[key]
        kinds = ["STRUCTURAL"]
        if node.get("interactive") or node.get("eventAttributes"):
            kinds.append("BEHAVIORAL")
        add_change(changes, "ADD", "NODE", key, kinds, ["node"], evidence, node=node, after=node_snapshot(node))
        counts["nodesAdded"] += 1
    for key in sorted(set(old_nodes) - set(new_nodes)):
        node = old_nodes[key]
        kinds = ["STRUCTURAL"]
        if node.get("interactive") or node.get("eventAttributes"):
            kinds.append("BEHAVIORAL")
        add_change(changes, "DELETE", "NODE", key, kinds, ["node"], evidence, node=node, before=node_snapshot(node))
        counts["nodesDeleted"] += 1
    for key in sorted(set(old_nodes) & set(new_nodes)):
        before = old_nodes[key]
        after = new_nodes[key]
        kinds, fields = classify_node_fields(before, after)
        if fields:
            action = "MOVE" if set(fields) <= {"parentNodeId", "domPath"} else "MODIFY"
            add_change(changes, action, "NODE", key, kinds, fields, evidence, node=after, before=node_snapshot(before), after=node_snapshot(after))
            counts["nodesModified"] += 1
    def binding_key(binding: dict[str, Any]) -> str:
        return f"{binding.get('selector', '')}::{binding.get('event', '')}::{binding.get('handlerRef', '')}::{binding.get('source', '')}"
    old_bindings = {binding_key(item): item for item in previous.get("eventBindings", [])}
    new_bindings = {binding_key(item): item for item in current.get("eventBindings", [])}
    selector_to_node = {node.get("selector"): node for node in current.get("nodes", [])}
    for key in sorted(set(new_bindings) - set(old_bindings)):
        binding = new_bindings[key]
        node = selector_to_node.get(binding.get("selector"))
        add_change(changes, "ADD", "EVENT", key, ["BEHAVIORAL"], ["eventBinding"], evidence, node=node, after=binding)
        counts["eventsChanged"] += 1
    for key in sorted(set(old_bindings) - set(new_bindings)):
        binding = old_bindings[key]
        node = selector_to_node.get(binding.get("selector"))
        add_change(changes, "DELETE", "EVENT", key, ["BEHAVIORAL"], ["eventBinding"], evidence, node=node, before=binding)
        counts["eventsChanged"] += 1
    def indicator_key(item: dict[str, Any]) -> str:
        return f"{item.get('nodeId', '')}::{item.get('kind', '')}::{item.get('text', '')}"
    old_states = {indicator_key(item): item for item in previous.get("stateIndicators", [])}
    new_states = {indicator_key(item): item for item in current.get("stateIndicators", [])}
    node_by_id = {node.get("nodeId"): node for node in current.get("nodes", [])}
    for key in sorted(set(new_states) - set(old_states)):
        item = new_states[key]
        add_change(changes, "ADD", "STATE", key, ["RUNTIME"], ["stateIndicator"], evidence, node=node_by_id.get(item.get("nodeId")), after=item)
        counts["statesChanged"] += 1
    for key in sorted(set(old_states) - set(new_states)):
        item = old_states[key]
        add_change(changes, "DELETE", "STATE", key, ["RUNTIME"], ["stateIndicator"], evidence, node=node_by_id.get(item.get("nodeId")), before=item)
        counts["statesChanged"] += 1
    old_scripts = {item.get("scriptId"): item for item in previous.get("scripts", [])}
    new_scripts = {item.get("scriptId"): item for item in current.get("scripts", [])}
    for key in sorted(set(old_scripts) | set(new_scripts)):
        before = old_scripts.get(key)
        after = new_scripts.get(key)
        if before == after:
            continue
        action = "ADD" if before is None else ("DELETE" if after is None else "MODIFY")
        add_change(changes, action, "SCRIPT", key or "script-unknown", ["BEHAVIORAL"], ["script"], evidence, before=before, after=after)
        counts["scriptsChanged"] += 1
    all_kinds = sorted({kind for item in changes for kind in item["changeKinds"]}, key=lambda item: PRECEDENCE[item])
    if not all_kinds:
        all_kinds = ["COSMETIC"]
    primary = max(all_kinds, key=lambda item: PRECEDENCE[item])
    requires_prd = primary in {"BEHAVIORAL", "DATA_CONTRACT", "PERMISSION", "POLICY"}
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "changeSetId": "CHANGESET-" + canonical_hash({"previous": previous.get("prototypeHash"), "current": current.get("prototypeHash"), "changes": changes})[:16],
        "workflowId": str(workflow_id or current.get("workflowId") or previous.get("workflowId") or "unknown"),
        "fromRevision": str(from_revision or previous.get("prototypeRevision") or previous.get("revision") or "previous"),
        "toRevision": str(to_revision or current.get("prototypeRevision") or current.get("revision") or "current"),
        "source": {
            "previousModelPath": str(previous_model_path),
            "previousModelHash": sha256_file(previous_model_path),
            "currentModelPath": str(current_model_path),
            "currentModelHash": sha256_file(current_model_path),
            "previousPrototypeHash": previous.get("prototypeHash", "0" * 64),
            "currentPrototypeHash": current.get("prototypeHash", "0" * 64),
        },
        "changeTypes": all_kinds,
        "primaryType": primary,
        "requiresPrdReconciliation": requires_prd,
        "changes": changes,
        "noOp": not changes,
        "metrics": {"changes": len(changes), **counts},
        "createdAt": now(),
    }
    return payload


def build_impact_report(change_set: dict[str, Any], current_model: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest_elements = {item.get("uiElementId"): item for item in (manifest or {}).get("elements", [])}
    affected_ui = sorted({item.get("uiElementId") for item in change_set.get("changes", []) if item.get("uiElementId")})
    missing_ui = [item.get("changeId") for item in change_set.get("changes", []) if item.get("targetType") != "SCRIPT" and not item.get("uiElementId")]
    affected_nodes = sorted({item.get("nodeId") for item in change_set.get("changes", []) if item.get("nodeId")})
    affected_fr: set[str] = set()
    affected_ac: set[str] = set()
    for ui_id in affected_ui:
        element = manifest_elements.get(ui_id, {})
        affected_fr.update(str(item) for item in element.get("frIds", []))
        affected_ac.update(str(item) for item in element.get("acIds", []))
    affected_events = sorted({item.get("targetKey", "") for item in change_set.get("changes", []) if item.get("targetType") == "EVENT"})
    affected_states = sorted({item.get("targetKey", "") for item in change_set.get("changes", []) if item.get("targetType") == "STATE"})
    artifacts = [str(current_model.get("prototypePath", "prototype.html"))]
    change_types = change_set.get("changeTypes", [])
    consumers: set[str] = {"PROTOTYPE"}
    reruns: set[str] = set()
    for kind in change_types:
        reruns.update(RERUN_RULES.get(kind, ["SEMANTIC_REVIEW"]))
        if kind == "BEHAVIORAL":
            consumers.add("INTERACTION_CONTRACT")
            consumers.add("RUNTIME_EVIDENCE")
            consumers.add("TEST_PLAN")
        if kind == "RUNTIME":
            consumers.add("RUNTIME_EVIDENCE")
        if kind == "PERMISSION":
            consumers.add("PRD")
            consumers.add("TEST_PLAN")
            consumers.add("RUNTIME_EVIDENCE")
        if kind == "DATA_CONTRACT":
            consumers.add("PRD")
            consumers.add("OVERVIEW")
            consumers.add("JIRA")
            consumers.add("TEST_PLAN")
        if kind == "STRUCTURAL":
            consumers.add("OVERVIEW")
        if kind == "POLICY":
            consumers.update({"PRD", "OVERVIEW", "JIRA", "TEST_PLAN", "RUNTIME_EVIDENCE"})
    if affected_fr or affected_ac or change_set.get("requiresPrdReconciliation"):
        consumers.add("PRD")
    if affected_fr or affected_ac:
        consumers.update({"OVERVIEW", "JIRA"})
    risk = "LOW"
    if change_types == ["COSMETIC"]:
        risk = "LOW"
    elif "PERMISSION" in change_types or "POLICY" in change_types:
        risk = "CRITICAL"
    elif any(kind in {"BEHAVIORAL", "DATA_CONTRACT", "RUNTIME"} for kind in change_types):
        risk = "HIGH"
    elif "STRUCTURAL" in change_types:
        risk = "MEDIUM"
    status = "BLOCKED" if missing_ui or (manifest is None and affected_ui) else "PASS"
    rationale = [f"primary change type: {change_set.get('primaryType')}", f"affected UI elements: {len(affected_ui)}", f"affected FR/AC: {len(affected_fr)}/{len(affected_ac)}"]
    if missing_ui:
        rationale.append("Some changes cannot be mapped to a stable UI element ID.")
    if manifest is None and affected_ui:
        rationale.append("Prototype Manifest is required to resolve FR/AC impact and protected consumers.")
    return {
        "schemaVersion": 1,
        "impactReportId": "IMPACT-" + canonical_hash({"changeSetId": change_set.get("changeSetId"), "affectedUi": affected_ui, "types": change_types})[:16],
        "changeSetId": str(change_set.get("changeSetId")),
        "status": status,
        "riskLevel": risk,
        "affected": {
            "uiElementIds": affected_ui,
            "nodeIds": affected_nodes,
            "frIds": sorted(affected_fr),
            "acIds": sorted(affected_ac),
            "events": affected_events,
            "states": affected_states,
            "artifacts": artifacts,
        },
        "consumers": sorted(consumers),
        "requiredReruns": sorted(reruns),
        "requiresFullGate": True,
        "rationale": rationale + ([f"unmapped changes: {len(missing_ui)}; sample: {', '.join(missing_ui[:10])}"] if missing_ui else []),
        "createdAt": now(),
    }


def build_patch_scope(change_set: dict[str, Any], impact: dict[str, Any], current_model: dict[str, Any], prototype: Path, max_changed_characters: int = 20000) -> dict[str, Any]:
    allowed_ui = sorted(set(impact.get("affected", {}).get("uiElementIds", [])))
    allowed_nodes = []
    selectors = []
    for node in current_model.get("nodes", []):
        if node.get("dataAiId") in allowed_ui:
            allowed_nodes.append(node.get("nodeId"))
            selectors.append(node.get("selector", node.get("domPath")))
    return {
        "schemaVersion": 1,
        "scopeId": "SCOPE-" + canonical_hash({"changeSetId": change_set.get("changeSetId"), "ui": allowed_ui, "types": change_set.get("changeTypes")})[:16],
        "changeSetId": str(change_set.get("changeSetId")),
        "targetArtifact": str(prototype.resolve()),
        "targetHash": sha256_file(prototype.resolve()),
        "allowedUIElementIds": allowed_ui,
        "allowedNodeIds": sorted(set(allowed_nodes)),
        "allowedSelectors": sorted(set(selectors)),
        "allowedChangeKinds": list(change_set.get("changeTypes", [])),
        "maxChangedCharacters": max_changed_characters,
        "createdAt": now(),
    }


def build_context_pack(current_model: dict[str, Any], change_set: dict[str, Any], impact: dict[str, Any], scope: dict[str, Any], token_budget: int = 4000) -> dict[str, Any]:
    nodes = current_model.get("nodes", [])
    node_by_id = {node.get("nodeId"): node for node in nodes}
    selected: dict[str, str] = {}
    allowed_ui = set(scope.get("allowedUIElementIds", []))
    for node in nodes:
        if node.get("dataAiId") in allowed_ui or node.get("nodeId") in set(scope.get("allowedNodeIds", [])):
            selected[node["nodeId"]] = "affected"
    for node_id in list(selected):
        current = node_by_id.get(node_id)
        while current and current.get("parentNodeId"):
            parent = node_by_id.get(current["parentNodeId"])
            if not parent:
                break
            selected.setdefault(parent["nodeId"], "ancestor")
            current = parent
    allowed_node_ids = set(scope.get("allowedNodeIds", []))
    for node in nodes:
        if node.get("parentNodeId") in allowed_node_ids:
            selected.setdefault(node["nodeId"], "descendant")
    indicator_nodes = {item.get("nodeId") for item in current_model.get("stateIndicators", []) if item.get("kind") in {"loading", "empty", "error", "timeout", "no-permission", "success", "validation-error"}}
    for node_id in indicator_nodes:
        if node_id in node_by_id and any(node_by_id[node_id].get("parentNodeId") == parent for parent in allowed_node_ids):
            selected.setdefault(node_id, "state-source")
    selected_nodes = []
    for node_id, reason in sorted(selected.items(), key=lambda item: node_by_id[item[0]].get("startOffset", 0) if item[0] in node_by_id else 0):
        node = node_by_id.get(node_id)
        if not node:
            continue
        selected_nodes.append({
            "nodeId": node["nodeId"],
            **({"uiElementId": node["dataAiId"]} if node.get("dataAiId") else {}),
            "selector": node.get("selector", node.get("domPath", "")),
            "tag": node.get("tag", ""),
            **({"text": node.get("text", "")[:500]} if node.get("text") else {}),
            "startOffset": int(node.get("startOffset", 0)),
            "endOffset": int(node.get("endOffset", 0)),
            "reason": reason,
        })
    omitted = [{"nodeId": node["nodeId"], "reason": "outside-patch-scope"} for node in nodes if node.get("nodeId") not in selected]
    dependency_closure = sorted(set(
        [str(change_set.get("changeSetId", "")), str(impact.get("impactReportId", "")), str(scope.get("scopeId", ""))]
        + list(impact.get("affected", {}).get("frIds", []))
        + list(impact.get("affected", {}).get("acIds", []))
        + list(impact.get("affected", {}).get("events", []))
        + list(impact.get("affected", {}).get("states", []))
    ))
    payload_without_hash = {
        "schemaVersion": 2,
        "packId": "PROTOTYPE-CONTEXT-" + canonical_hash({"changeSetId": change_set.get("changeSetId"), "scopeId": scope.get("scopeId")})[:16],
        "workflowId": str(change_set.get("workflowId")),
        "revision": str(change_set.get("toRevision")),
        "taskPurpose": "SCOPED_PATCH",
        "sourceArtifacts": [
            {"path": str(current_model.get("prototypePath", "")), "sha256": current_model.get("prototypeHash", "0" * 64)},
            {"path": str(change_set.get("source", {}).get("currentModelPath", "")), "sha256": change_set.get("source", {}).get("currentModelHash", "0" * 64)},
        ],
        "selectedNodes": selected_nodes,
        "omittedNodes": omitted,
        "dependencyClosure": dependency_closure,
        "allowedPatchScopes": list(scope.get("allowedSelectors", [])),
        "tokenBudget": token_budget,
    }
    estimated = max(1, len(json.dumps(payload_without_hash, ensure_ascii=False)) // 4)
    return {
        **payload_without_hash,
        "estimatedTokens": estimated,
        "withinTokenBudget": estimated <= token_budget,
        "contextHash": canonical_hash(payload_without_hash),
        "createdAt": now(),
    }


def apply_patch(prototype: Path, current_model: Path, scope: dict[str, Any], patch: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    prototype = prototype.resolve()
    document = prototype.read_text(encoding="utf-8", errors="strict")
    before_hash = sha256_file(prototype)
    errors: list[str] = []
    if scope.get("changeSetId") != patch.get("changeSetId"):
        errors.append("changeSetId mismatch between scope and patch")
    if scope.get("scopeId") != patch.get("scopeId"):
        errors.append("scopeId mismatch between scope and patch")
    if scope.get("targetHash") != before_hash:
        errors.append("prototype hash does not match patch scope targetHash")
    if patch.get("basePrototypeHash") != before_hash:
        errors.append("prototype hash does not match patch basePrototypeHash")
    model = load(current_model.resolve())
    node_by_id = {node.get("nodeId"): node for node in model.get("nodes", [])}
    allowed_ui = set(scope.get("allowedUIElementIds", []))
    allowed_nodes = set(scope.get("allowedNodeIds", []))
    allowed_kinds = set(scope.get("allowedChangeKinds", []))
    edits: list[tuple[int, int, str, dict[str, Any]]] = []
    changed_characters = 0
    for operation in patch.get("operations", []):
        ui_id = operation.get("uiElementId")
        kind = operation.get("changeKind")
        if ui_id not in allowed_ui:
            errors.append(f"operation {operation.get('operationId')} targets UI element outside scope: {ui_id}")
            continue
        if kind not in allowed_kinds:
            errors.append(f"operation {operation.get('operationId')} uses change kind outside scope: {kind}")
            continue
        target_nodes = [node for node in model.get("nodes", []) if node.get("dataAiId") == ui_id or (operation.get("nodeId") and node.get("nodeId") == operation.get("nodeId"))]
        if not target_nodes:
            errors.append(f"operation {operation.get('operationId')} has no matching DOM node for {ui_id}")
            continue
        if len(target_nodes) > 1:
            errors.append(f"operation {operation.get('operationId')} matches multiple DOM nodes for {ui_id}; nodeId is required")
            continue
        node = target_nodes[0]
        if node.get("nodeId") not in allowed_nodes:
            errors.append(f"operation {operation.get('operationId')} targets node outside scope: {node.get('nodeId')}")
            continue
        start = int(node.get("startOffset", 0))
        end = int(node.get("endOffset", len(document)))
        segment = document[start:end]
        old_text = operation.get("oldText", "")
        new_text = operation.get("newText", "")
        count = segment.count(old_text)
        if count != 1:
            errors.append(f"operation {operation.get('operationId')} oldText count in target scope is {count}, expected 1")
            continue
        local_start = segment.find(old_text)
        absolute_start = start + local_start
        absolute_end = absolute_start + len(old_text)
        for other_start, other_end, _, _ in edits:
            if absolute_start < other_end and other_start < absolute_end:
                errors.append(f"operation {operation.get('operationId')} overlaps another patch operation")
                break
        else:
            edits.append((absolute_start, absolute_end, new_text, operation))
            changed_characters += max(len(old_text), len(new_text))
    if changed_characters > int(scope.get("maxChangedCharacters", 0)):
        errors.append(f"patch changes {changed_characters} characters, above scope limit {scope.get('maxChangedCharacters')}")
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "FAIL",
        "prototypePath": str(prototype),
        "scopeId": scope.get("scopeId"),
        "patchId": patch.get("patchId"),
        "beforeHash": before_hash,
        "appliedOperations": 0 if errors else len(edits),
        "changedCharacters": changed_characters,
        "errors": errors,
        "checkedAt": now(),
    }
    if errors:
        return document, result
    patched = document
    for start, end, replacement, _ in sorted(edits, key=lambda item: item[0], reverse=True):
        patched = patched[:start] + replacement + patched[end:]
    result["afterHash"] = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    return patched, result
