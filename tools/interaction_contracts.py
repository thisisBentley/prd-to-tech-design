#!/usr/bin/env python3
"""Prototype DOM extraction and Interaction Contract V2 helpers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from validate_json_schemas import load as schema_load, validate as schema_validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary"}
EVENT_ATTRS = {
    "onclick": "click",
    "ondblclick": "dblclick",
    "onchange": "change",
    "oninput": "input",
    "onsubmit": "submit",
    "onkeydown": "keydown",
    "onkeyup": "keyup",
    "onfocus": "focus",
    "onblur": "blur",
    "onmouseover": "mouseover",
}
STATE_PATTERNS = {
    "loading": re.compile(r"loading|加载中|正在加载", re.I),
    "empty": re.compile(r"empty|暂无|无数据|空态", re.I),
    "error": re.compile(r"error|失败|异常|错误", re.I),
    "timeout": re.compile(r"timeout|超时", re.I),
    "no-permission": re.compile(r"unauthorized|no.?permission|无权限|未授权", re.I),
    "success": re.compile(r"success|成功|已完成", re.I),
    "validation-error": re.compile(r"validation.?error|校验失败|输入错误", re.I),
}
CUSTOM_STATE_RE = re.compile(r"(?:data-|class=|id=)([A-Za-z0-9_-]*(?:state|status|mode|fallback|error|loading|empty)[A-Za-z0-9_-]*)", re.I)


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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def schema(name: str) -> dict[str, Any]:
    return schema_load(SCHEMA_DIR / name)


def validate_schema_value(value: Any, schema_name: str) -> list[str]:
    document = schema(schema_name)
    return schema_validate(value, document, document)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def safe_attribute(value: str) -> str:
    if len(value) <= 500:
        return value
    return f"<truncated:{sha256_text(value)[:16]}:{len(value)}>"


class PrototypeHTMLParser(HTMLParser):
    def __init__(self, document: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.document = document
        self.line_offsets = [0]
        for line in document.splitlines(keepends=True):
            self.line_offsets.append(self.line_offsets[-1] + len(line))
        self.nodes: list[dict[str, Any]] = []
        self.scripts: list[dict[str, Any]] = []
        self.stack: list[int] = []
        self.child_counts: dict[tuple[int | None, str], int] = {}
        self.script_buffer: list[str] = []
        self.in_script = False
        self.title_buffer: list[str] = []
        self.in_title = False
        self.prd_version: str | None = None

    def source_offset(self, position: tuple[int, int]) -> int:
        line, column = position
        return self.line_offsets[min(max(line - 1, 0), len(self.line_offsets) - 1)] + column

    def tag_end(self, start: int) -> int:
        end = self.document.find(">", start)
        return len(self.document) if end < 0 else end + 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        start_offset = self.source_offset(self.getpos())
        opening_end = self.tag_end(start_offset)
        attr_map = {name.lower(): safe_attribute(value or "") for name, value in attrs}
        parent_index = self.stack[-1] if self.stack else None
        key = (parent_index, tag)
        self.child_counts[key] = self.child_counts.get(key, 0) + 1
        nth = self.child_counts[key]
        index = len(self.nodes)
        dom_parts: list[str] = []
        cursor = parent_index
        chain: list[tuple[int, str]] = []
        while cursor is not None:
            node = self.nodes[cursor]
            chain.append((int(node["siblingIndex"]), str(node["tag"])))
            cursor = node.get("parentIndex") if isinstance(node.get("parentIndex"), int) else None
        chain.append((nth, tag))
        for sibling_index, chain_tag in reversed(chain):
            dom_parts.append(f"{chain_tag}:nth-of-type({sibling_index})")
        dom_path = " > ".join(dom_parts)
        data_ai_id = attr_map.get("data-ai-id", "").strip()
        node_id = attr_map.get("id", "").strip()
        data_testid = attr_map.get("data-testid", "").strip()
        selector = f'[data-ai-id="{data_ai_id}"]' if data_ai_id else (f"#{node_id}" if node_id else (f'[data-testid="{data_testid}"]' if data_testid else dom_path))
        event_attributes = {name: value for name, value in attr_map.items() if name in EVENT_ATTRS}
        role = attr_map.get("role", "").lower()
        interactive = tag in INTERACTIVE_TAGS or role in {"button", "link", "menuitem", "tab"} or bool(event_attributes)
        text_hint = ""
        for name in ("aria-label", "title", "placeholder", "alt", "value"):
            if attr_map.get(name):
                text_hint = attr_map[name]
                break
        node = {
            "nodeId": f"DOM-{index + 1:05d}",
            "index": index,
            "tag": tag,
            "classes": attr_map.get("class", "").split(),
            "attributes": attr_map,
            "domPath": dom_path,
            "selector": selector,
            "interactive": interactive,
            "eventAttributes": event_attributes,
            "textChunks": [text_hint] if text_hint else [],
            "siblingIndex": nth,
            "startOffset": start_offset,
            "endOffset": opening_end if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"} else len(self.document),
        }
        if parent_index is not None:
            node["parentNodeId"] = self.nodes[parent_index]["nodeId"]
            node["parentIndex"] = parent_index
        if data_ai_id:
            node["dataAiId"] = data_ai_id
        if node_id:
            node["id"] = node_id
        self.nodes.append(node)
        self.stack.append(index)
        if tag == "script":
            self.in_script = True
            self.script_buffer = []
        if tag == "title":
            self.in_title = True
            self.title_buffer = []
        content = attr_map.get("content", "")
        if attr_map.get("name") == "source-prd-version" and content:
            self.prd_version = content

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.nodes[self.stack[-1]]["tag"] == tag.lower():
            index = self.stack.pop()
            self.nodes[index]["endOffset"] = self.tag_end(self.nodes[index]["startOffset"])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self.in_script:
            script_text = "".join(self.script_buffer)
            functions = sorted(set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", script_text)))
            functions += sorted(set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", script_text)))
            variables = sorted(set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", script_text)))
            self.scripts.append({
                "scriptId": f"SCRIPT-{len(self.scripts) + 1:03d}",
                "sha256": sha256_text(script_text),
                "functionNames": sorted(set(functions)),
                "stateVariables": variables,
                "lineCount": len(script_text.splitlines()),
                "text": script_text,
            })
            self.in_script = False
            self.script_buffer = []
        if tag == "title" and self.in_title:
            self.in_title = False
        end_offset = self.tag_end(self.source_offset(self.getpos()))
        for position in range(len(self.stack) - 1, -1, -1):
            index = self.stack[position]
            if self.nodes[index]["tag"] == tag:
                self.nodes[index]["endOffset"] = end_offset
                del self.stack[position:]
                break

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.script_buffer.append(data)
            return
        if self.in_title:
            self.title_buffer.append(data)
        text = clean_text(data)
        if not text:
            return
        for index in self.stack:
            node = self.nodes[index]
            if node["tag"] in {"script", "style"}:
                continue
            chunks = node.setdefault("textChunks", [])
            if len(chunks) < 20:
                chunks.append(text[:300])
        if self.stack:
            own_node = self.nodes[self.stack[-1]]
            own_chunks = own_node.setdefault("ownTextChunks", [])
            if len(own_chunks) < 20:
                own_chunks.append(text[:300])

    def finalize(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str | None]:
        nodes = []
        for node in self.nodes:
            text = clean_text(" ".join(node.pop("textChunks", [])))[:1000]
            own_text = clean_text(" ".join(node.pop("ownTextChunks", [])))[:1000]
            node.pop("siblingIndex", None)
            node.pop("parentIndex", None)
            if text:
                node["text"] = text
            if own_text:
                node["ownText"] = own_text
            nodes.append(node)
        return nodes, [dict(script) for script in self.scripts], clean_text("".join(self.title_buffer)), self.prd_version


def extract_event_bindings(nodes: list[dict[str, Any]], scripts: list[dict[str, Any]], prototype: Path) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    selector_by_node = {node["nodeId"]: node.get("selector", node["domPath"]) for node in nodes}
    for node in nodes:
        for attr, value in (node.get("eventAttributes") or {}).items():
            event = EVENT_ATTRS.get(attr, attr.removeprefix("on"))
            bindings.append({
                "bindingId": f"BIND-{len(bindings) + 1:04d}",
                "event": event,
                "source": "inline",
                "selector": selector_by_node[node["nodeId"]],
                "handlerRef": value[:200],
                "evidenceRefs": [f"{prototype}#{node['nodeId']}"],
            })
    script_text = "\n".join(script.get("text", "") for script in scripts)
    patterns = [
        re.compile(r"(?:querySelector|closest)\(\s*['\"]([^'\"]+)['\"]\s*\).*?addEventListener\(\s*['\"]([A-Za-z0-9_-]+)['\"]", re.S),
        re.compile(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\).*?addEventListener\(\s*['\"]([A-Za-z0-9_-]+)['\"]", re.S),
        re.compile(r"\$\(\s*['\"]([^'\"]+)['\"]\s*\).*?\.on\(\s*['\"]([A-Za-z0-9_-]+)['\"]", re.S),
    ]
    for pattern in patterns:
        for selector, event in pattern.findall(script_text):
            if selector.startswith("#") or selector.startswith(".") or selector.startswith("["):
                normalized_selector = selector
            else:
                normalized_selector = f"#{selector}"
            bindings.append({
                "bindingId": f"BIND-{len(bindings) + 1:04d}",
                "event": event.lower(),
                "source": "script",
                "selector": normalized_selector,
                "evidenceRefs": [str(prototype)],
            })
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for binding in bindings:
        unique[(binding["selector"], binding["event"])] = binding
    return [unique[key] for key in sorted(unique)]


def extract_state_indicators(nodes: list[dict[str, Any]], prototype: Path) -> list[dict[str, Any]]:
    indicators: list[dict[str, Any]] = []
    parent_ids = {node.get("parentNodeId") for node in nodes if node.get("parentNodeId")}
    for node in nodes:
        text_evidence = node.get("ownText", "")
        haystack = " ".join([
            node.get("id", ""),
            " ".join(node.get("classes", [])),
            " ".join(f"{key}={value}" for key, value in (node.get("attributes") or {}).items()),
            text_evidence,
        ])
        matched_kinds: list[str] = []
        for kind, pattern in STATE_PATTERNS.items():
            if pattern.search(haystack):
                matched_kinds.append(kind)
        if not matched_kinds:
            custom_markers = ("state", "status", "fallback", "timeout", "loading", "empty", "error")
            custom = any(
                any(marker in str(key).lower() for marker in custom_markers)
                for key in (node.get("attributes") or {})
            ) or any(any(marker in token.lower() for marker in custom_markers) for token in node.get("classes", []))
            if custom:
                matched_kinds.append("custom")
        for kind in dict.fromkeys(matched_kinds):
            indicators.append({
                "indicatorId": f"STATE-{len(indicators) + 1:04d}",
                "kind": kind,
                "nodeId": node["nodeId"],
                "text": node.get("text", "")[:200],
                "evidenceRefs": [f"{prototype}#{node['nodeId']}"],
            })
    return indicators


def build_model(prototype: Path) -> dict[str, Any]:
    prototype = prototype.resolve()
    text = prototype.read_text(encoding="utf-8", errors="replace")
    parser = PrototypeHTMLParser(text)
    parser.feed(text)
    parser.close()
    nodes, scripts_with_text, title, prd_version = parser.finalize()
    event_bindings = extract_event_bindings(nodes, scripts_with_text, prototype)
    state_indicators = extract_state_indicators(nodes, prototype)
    scripts = []
    for script in scripts_with_text:
        normalized = dict(script)
        normalized.pop("text", None)
        scripts.append(normalized)
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "modelId": f"prototype-model-{sha256_file(prototype)[:16]}",
        "prototypePath": str(prototype),
        "prototypeHash": sha256_file(prototype),
        "title": title,
        "nodes": nodes,
        "scripts": scripts,
        "eventBindings": event_bindings,
        "stateIndicators": state_indicators,
        "metrics": {
            "nodes": len(nodes),
            "interactiveNodes": sum(1 for node in nodes if node.get("interactive")),
            "dataAiIdNodes": sum(1 for node in nodes if node.get("dataAiId")),
            "scripts": len(scripts),
            "eventBindings": len(event_bindings),
            "stateIndicators": len(state_indicators),
        },
        "createdAt": now(),
    }
    if prd_version:
        payload["prdVersion"] = prd_version
    return payload


def normalize_label(value: str) -> str:
    return re.sub(r"[\s\-_/·:：()（）]+", "", value).lower()


def match_element(element: dict[str, Any], nodes: list[dict[str, Any]], used: set[str]) -> tuple[dict[str, Any] | None, str]:
    ui_id = str(element.get("uiElementId", ""))
    for node in nodes:
        if node.get("dataAiId") == ui_id and node["nodeId"] not in used:
            return node, "data-ai-id"
    for node in nodes:
        if node.get("id") == ui_id and node["nodeId"] not in used:
            return node, "id"
    for node in nodes:
        if (node.get("attributes") or {}).get("data-testid") == ui_id and node["nodeId"] not in used:
            return node, "data-testid"
    label = normalize_label(str(element.get("visibleLabel", "")))
    if label:
        candidates = []
        for node in nodes:
            if node["nodeId"] in used:
                continue
            haystack = normalize_label(" ".join([node.get("text", ""), (node.get("attributes") or {}).get("aria-label", ""), (node.get("attributes") or {}).get("title", "")]))
            if haystack and (haystack == label or label in haystack):
                candidates.append(node)
        if candidates:
            candidates.sort(key=lambda node: (0 if node.get("interactive") else 1, len(node.get("text", ""))))
            return candidates[0], "visible-label"
    return None, "unbound"


def normalize_event_type(action: str) -> str:
    value = str(action or "").strip().lower()
    mapping = {
        "click": "click",
        "input": "input",
        "change": "change",
        "submit": "submit",
        "select": "change",
        "toggle": "click",
        "open": "click",
        "close": "click",
        "navigate": "click",
    }
    return mapping.get(value, value or "click")


def merge_overlay_event(overlay_event: dict[str, Any] | None) -> dict[str, Any]:
    source = overlay_event or {}
    return {
        "preconditions": [str(item) for item in source.get("preconditions", []) if str(item).strip()],
        "postconditions": [str(item) for item in source.get("postconditions", []) if str(item).strip()],
        "stateTransitions": list(source.get("stateTransitions", []) or []),
        "dataEffects": list(source.get("dataEffects", []) or []),
        "runtimeScenarioIds": [str(item) for item in source.get("runtimeScenarioIds", []) if str(item).strip()],
    }


def build_contract(
    prototype: Path,
    model_path: Path,
    manifest_path: Path,
    overlay_path: Path | None = None,
    prd_path: Path | None = None,
) -> dict[str, Any]:
    prototype = prototype.resolve()
    model_path = model_path.resolve()
    manifest_path = manifest_path.resolve()
    model = load(model_path)
    manifest = load(manifest_path)
    overlay = load(overlay_path.resolve()) if overlay_path else {"elements": [], "runtimeScenarios": []}
    prd_text = prd_path.resolve().read_text(encoding="utf-8", errors="replace") if prd_path else ""
    prd_fr = set(re.findall(r"FR-\d{3}", prd_text))
    prd_ac = set(re.findall(r"AC-\d{3}", prd_text))
    overlay_elements = {item.get("uiElementId"): item for item in overlay.get("elements", []) if isinstance(item, dict)}
    scenario_map = {item.get("scenarioId"): item for item in overlay.get("runtimeScenarios", []) if isinstance(item, dict)}
    nodes = model.get("nodes", [])
    used_nodes: set[str] = set()
    elements: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    dangling_fr: set[str] = set()
    dangling_ac: set[str] = set()

    def finding(code: str, message: str, evidence_refs: list[str], element_id: str | None = None, event_id: str | None = None, severity: str = "BLOCKING") -> None:
        findings.append({
            "findingId": f"ICF-{len(findings) + 1:04d}",
            "severity": severity,
            "code": code,
            "message": message,
            "evidenceRefs": evidence_refs or [str(manifest_path)],
            **({"elementId": element_id} if element_id else {}),
            **({"eventId": event_id} if event_id else {}),
        })

    for manifest_element in manifest.get("elements", []):
        ui_id = str(manifest_element.get("uiElementId", ""))
        if ui_id in seen_ids:
            finding("DUPLICATE_UI_ELEMENT_ID", f"Duplicate UI element ID: {ui_id}", [str(manifest_path)], ui_id)
        seen_ids.add(ui_id)
        node, match_method = match_element(manifest_element, nodes, used_nodes)
        if node:
            used_nodes.add(node["nodeId"])
        selector = node.get("selector", "") if node else ""
        if not node:
            finding("UNBOUND_DOM_ELEMENT", f"Manifest element {ui_id} has no matching DOM node.", [str(manifest_path), str(model_path)], ui_id)
        overlay_element = overlay_elements.get(ui_id, {})
        permission_roles = [str(item) for item in overlay_element.get("permissionRoles", []) if str(item).strip()]
        if not permission_roles:
            permission_roles = [str(item) for item in manifest_element.get("permissions", []) if str(item).strip()]
        if not permission_roles:
            finding("MISSING_PERMISSION_ROLES", f"Element {ui_id} has no permission roles.", [str(manifest_path)], ui_id)
        action = str(manifest_element.get("action", "")).strip()
        events: list[dict[str, Any]] = []
        overlay_events = {str(item.get("type")): item for item in overlay_element.get("events", []) if isinstance(item, dict)}
        overlay_event = overlay_events.get(normalize_event_type(action)) or next(iter(overlay_events.values()), None)
        if action:
            event_type = normalize_event_type(action)
            event_id = f"EVT-{ui_id.replace('UI-', '')}-{event_type}".replace("--", "-")
            merged = merge_overlay_event(overlay_event)
            handler_ref = ""
            for binding in model.get("eventBindings", []):
                if selector and binding.get("selector") == selector and binding.get("event") == event_type:
                    handler_ref = str(binding.get("handlerRef", ""))
                    break
            event = {
                "eventId": event_id,
                "type": event_type,
                **({"handlerRef": handler_ref} if handler_ref else {}),
                "preconditions": merged["preconditions"],
                "postconditions": merged["postconditions"],
                "stateTransitions": merged["stateTransitions"],
                "dataEffects": merged["dataEffects"],
                "runtimeScenarioIds": merged["runtimeScenarioIds"],
            }
            events.append(event)
            if not merged["postconditions"]:
                finding("MISSING_POSTCONDITION", f"Event {event_id} has no postcondition.", [str(manifest_path), str(model_path)], ui_id, event_id)
            if not merged["runtimeScenarioIds"]:
                finding("MISSING_RUNTIME_SCENARIO", f"Event {event_id} has no runtime scenario.", [str(manifest_path), str(model_path)], ui_id, event_id)
        render_states = []
        state_names = [str(item) for item in manifest_element.get("states", []) if str(item).strip()]
        overlay_states = [str(item) for item in overlay_element.get("renderStates", []) if str(item).strip()]
        state_names = list(dict.fromkeys([*state_names, *overlay_states]))
        indicator_kinds = {item.get("kind") for item in model.get("stateIndicators", [])}
        for state in state_names:
            matched_kind = next((kind for kind in indicator_kinds if normalize_label(kind) == normalize_label(state) or normalize_label(kind) in normalize_label(state)), None)
            refs = [f"{prototype}#{node['nodeId']}"] if node else [str(prototype)]
            if matched_kind:
                refs = next((item.get("evidenceRefs", refs) for item in model.get("stateIndicators", []) if item.get("kind") == matched_kind), refs)
            render_states.append({"state": state, "evidenceRefs": refs})
        fr_ids = [str(item) for item in manifest_element.get("frIds", [])]
        ac_ids = [str(item) for item in manifest_element.get("acIds", [])]
        if prd_fr:
            dangling_fr.update(item for item in fr_ids if item not in prd_fr)
        if prd_ac:
            dangling_ac.update(item for item in ac_ids if item not in prd_ac)
        for scenario_id in (events[0]["runtimeScenarioIds"] if events else []):
            scenario = scenario_map.get(scenario_id)
            if not scenario:
                finding("MISSING_SCENARIO_DEFINITION", f"Runtime scenario {scenario_id} is referenced but not defined.", [str(overlay_path or manifest_path)], ui_id, events[0]["eventId"])
                continue
            candidate = dict(scenario)
            candidate["elementId"] = ui_id
            candidate["eventId"] = events[0]["eventId"]
            scenarios.append(candidate)
        elements.append({
            "uiElementId": ui_id,
            "visibleLabel": str(manifest_element.get("visibleLabel", ui_id)),
            "frIds": fr_ids,
            "acIds": ac_ids,
            "selector": selector,
            **({"domNodeId": node["nodeId"]} if node else {}),
            "matchMethod": match_method,
            "events": events,
            "renderStates": render_states,
            "permissionRoles": permission_roles,
        })
    for fr_id in sorted(dangling_fr):
        finding("DANGLING_FR_ID", f"FR {fr_id} does not exist in the PRD.", [str(prd_path)], severity="BLOCKING")
    for ac_id in sorted(dangling_ac):
        finding("DANGLING_AC_ID", f"AC {ac_id} does not exist in the PRD.", [str(prd_path)], severity="BLOCKING")
    # Validate that every overlay scenario not attached to an element is surfaced.
    attached = {item.get("scenarioId") for item in scenarios}
    for scenario_id in scenario_map:
        if scenario_id not in attached:
            finding("ORPHAN_RUNTIME_SCENARIO", f"Runtime scenario {scenario_id} is not attached to any element event.", [str(overlay_path or manifest_path)], severity="NON_BLOCKING")
    blocking = [item for item in findings if item["severity"] == "BLOCKING"]
    events = [event for element in elements for event in element.get("events", [])]
    metrics = {
        "elements": len(elements),
        "boundElements": sum(1 for element in elements if element["matchMethod"] != "unbound"),
        "unboundElements": sum(1 for element in elements if element["matchMethod"] == "unbound"),
        "events": len(events),
        "eventsWithPostconditions": sum(1 for event in events if event.get("postconditions")),
        "eventsWithRuntimeScenarios": sum(1 for event in events if event.get("runtimeScenarioIds")),
        "runtimeScenarios": len(scenarios),
        "blockingFindings": len(blocking),
        "danglingFrIds": len(dangling_fr),
        "danglingAcIds": len(dangling_ac),
    }
    return {
        "schemaVersion": 1,
        "contractId": f"interaction-contract-{sha256_file(prototype)[:12]}-{sha256_file(manifest_path)[:8]}",
        "workflowId": str(manifest.get("workflowId", "unknown")),
        "prototypeRevision": str(manifest.get("prototypeRevision", "unknown")),
        "status": "PASS" if not blocking else "INCOMPLETE",
        "source": {
            "prototypePath": str(prototype),
            "prototypeHash": sha256_file(prototype),
            "manifestPath": str(manifest_path),
            "manifestHash": sha256_file(manifest_path),
            "modelPath": str(model_path),
            "modelHash": sha256_file(model_path),
            **({"prdPath": str(prd_path.resolve()), "prdHash": sha256_file(prd_path.resolve())} if prd_path else {}),
        },
        "elements": elements,
        "runtimeScenarios": scenarios,
        "findings": findings,
        "metrics": metrics,
        "createdAt": now(),
    }


def validate_contract(contract: dict[str, Any], prd_path: Path | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def add(check_id: str, ok: bool, observed: Any, expected: Any) -> None:
        checks.append({"checkId": check_id, "status": "passed" if ok else "failed", "observed": observed, "expected": expected})
        if not ok:
            errors.append(f"{check_id}: expected {expected}; observed {observed}")

    schema_errors = validate_schema_value(contract, "interaction-contract.schema.json")
    add("IC.SCHEMA", not schema_errors, schema_errors or "valid", "interaction-contract.schema.json")
    elements = contract.get("elements", []) if isinstance(contract, dict) else []
    ids = [item.get("uiElementId") for item in elements]
    add("IC.UNIQUE_UI_IDS", len(ids) == len(set(ids)), len(ids) - len(set(ids)), "0 duplicate UI IDs")
    unbound = [item.get("uiElementId") for item in elements if item.get("matchMethod") == "unbound" or not item.get("selector")]
    add("IC.BOUND_ELEMENTS", not unbound, unbound, "every element bound to a DOM selector")
    event_rows = [(item.get("uiElementId"), event) for item in elements for event in item.get("events", [])]
    missing_post = [event.get("eventId") for _, event in event_rows if not event.get("postconditions")]
    add("IC.EVENT_POSTCONDITIONS", not missing_post, missing_post, "every event has at least one postcondition")
    missing_scenarios = [event.get("eventId") for _, event in event_rows if not event.get("runtimeScenarioIds")]
    add("IC.EVENT_RUNTIME_SCENARIOS", not missing_scenarios, missing_scenarios, "every event has a runtime scenario")
    scenario_ids = {item.get("scenarioId") for item in contract.get("runtimeScenarios", [])}
    referenced = {scenario_id for _, event in event_rows for scenario_id in event.get("runtimeScenarioIds", [])}
    add("IC.SCENARIO_REFERENCES", referenced <= scenario_ids, sorted(referenced - scenario_ids), "all referenced scenarios are defined")
    if prd_path:
        prd_text = prd_path.resolve().read_text(encoding="utf-8", errors="replace")
        known_fr = set(re.findall(r"FR-\d{3}", prd_text))
        known_ac = set(re.findall(r"AC-\d{3}", prd_text))
        dangling_fr = sorted({fr for item in elements for fr in item.get("frIds", []) if known_fr and fr not in known_fr})
        dangling_ac = sorted({ac for item in elements for ac in item.get("acIds", []) if known_ac and ac not in known_ac})
        add("IC.FR_REFERENCES", not dangling_fr, dangling_fr, "all FR IDs exist in PRD")
        add("IC.AC_REFERENCES", not dangling_ac, dangling_ac, "all AC IDs exist in PRD")
    blocking = [item for item in contract.get("findings", []) if item.get("severity") == "BLOCKING"]
    add("IC.STATUS_CONSISTENT", (contract.get("status") == "INCOMPLETE") == bool(blocking), {"status": contract.get("status"), "blocking": len(blocking)}, "status matches blocking findings")
    return {"schemaVersion": 1, "status": "PASS" if not errors else "FAIL", "checks": checks, "errors": errors, "metrics": contract.get("metrics", {}), "checkedAt": now()}
