#!/usr/bin/env python3
"""Decompose a frozen PRD and optional Prototype manifest into semantic units.

The model keeps one authority per unit and makes cross-unit references explicit.
It is intentionally deterministic: it extracts structure and bindings, while the
independent semantic reviewer remains responsible for meaning-level judgement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FR_RE = re.compile(r"^(#{1,6})\s+(?:\d+(?:\.\d+)*)\s+(FR-\d{3})\s*[：:]\s*(.+?)\s*$", re.M)
AC_RE = re.compile(r"^(#{1,6})\s+(?:\d+(?:\.\d+)*)\s+(AC-\d{3})\s+(.+?)\s*$", re.M)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
ID_RE = re.compile(r"\b(?:FR|AC)-\d{3}\b")
GOAL_ROW_RE = re.compile(r"^\|\s*(G-\d{3})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|", re.M)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def heading_matches(text: str) -> list[dict[str, Any]]:
    return [{"level": len(m.group(1)), "title": clean(m.group(2)), "start": m.start()} for m in HEADING_RE.finditer(text)]


def block_for(text: str, match: re.Match[str]) -> str:
    headings = heading_matches(text)
    current_level = len(match.group(1))
    start = match.end()
    end = len(text)
    for heading in headings:
        if heading["start"] <= match.start():
            continue
        if heading["level"] <= current_level:
            end = heading["start"]
            break
    return text[start:end].strip()


def section_by_title(text: str, pattern: str) -> tuple[str, str] | None:
    for match in HEADING_RE.finditer(text):
        title = clean(match.group(2))
        if re.search(pattern, title):
            return title, block_for(text, match)
    return None


def split_subsections(content: str) -> dict[str, str]:
    matches = list(re.finditer(r"^#{3,6}\s+(?:\d+(?:\.\d+)*)?\s*(.+?)\s*$", content, re.M))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = clean(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        result[title] = content[match.end():end].strip()
    return result


def parse_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    label_re = re.compile(r"^\s*[-*]?\s*(关联功能|前置条件|WHEN|THEN|验收方式)\s*[：:]\s*(.*)$", re.IGNORECASE)
    for line in content.splitlines():
        match = label_re.match(line)
        if match:
            if current is not None:
                fields[current] = clean(" ".join(buffer))
            current = match.group(1).upper()
            buffer = [match.group(2)]
        elif current is not None:
            stripped = line.strip()
            if stripped.startswith(("- ", "* ")):
                stripped = stripped[2:]
            if stripped:
                buffer.append(stripped)
    if current is not None:
        fields[current] = clean(" ".join(buffer))
    return fields


def expand_id_ranges(text: str) -> list[str]:
    ids: list[str] = []
    for prefix in ("FR", "AC"):
        for match in re.finditer(rf"\b{prefix}-(\d{{3}})\s*[–—~～-]\s*(?:{prefix}-)?(\d{{3}})\b", text):
            start, end = int(match.group(1)), int(match.group(2))
            if start <= end and end - start <= 200:
                ids.extend(f"{prefix}-{number:03d}" for number in range(start, end + 1))
    for value in ID_RE.findall(text):
        ids.append(value)
    return sorted(set(ids))


def extract_contracts(text: str, prd_path: Path) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    contract_specs = [
        ("GC-PERMISSIONS", "PERMISSION", r"角色与访问权限|权限矩阵"),
        ("GC-CAPABILITY-BASELINE", "CAPABILITY", r"既有能力承接|既有能力|回归基线"),
        ("GC-FEATURE-INDEX", "FEATURE_INDEX", r"功能需求总览"),
        ("GC-SCOPE", "SCOPE", r"本期范围|需求范围"),
        ("GC-GOALS", "GOALS", r"目标列表|总体目标"),
        ("GC-TERMINOLOGY", "TERMINOLOGY", r"术语|名词定义"),
        ("GC-ENUM", "ENUM", r"枚举|字典"),
    ]
    for contract_id, kind, pattern in contract_specs:
        found = section_by_title(text, pattern)
        if not found:
            continue
        title, content = found
        contracts.append({
            "contractId": contract_id,
            "kind": kind,
            "title": title,
            "statement": content,
            "sourceRef": f"{prd_path}#{title}",
            "authority": "PRD",
            "status": "ACTIVE",
        })
    state_blocks: list[str] = []
    for match in HEADING_RE.finditer(text):
        title = clean(match.group(2))
        if re.search(r"状态|状态流转|状态模型", title):
            block = block_for(text, match)
            if block:
                state_blocks.append(f"{title}: {block}")
    if state_blocks:
        contracts.append({
            "contractId": "GC-STATE-MODEL",
            "kind": "STATE",
            "title": "State model",
            "statement": "\n\n".join(state_blocks),
            "sourceRef": f"{prd_path}#state-model",
            "authority": "PRD",
            "status": "ACTIVE",
        })
    return contracts


def add_edge(edges: list[dict[str, Any]], from_id: str, to_id: str, relation: str, evidence: list[str]) -> None:
    key = (from_id, to_id, relation)
    if any((item["fromUnitId"], item["toUnitId"], item["relation"]) == key for item in edges):
        return
    edges.append({
        "edgeId": f"EDGE-{len(edges) + 1:04d}",
        "fromUnitId": from_id,
        "toUnitId": to_id,
        "relation": relation,
        "status": "ACTIVE",
        "evidenceRefs": evidence,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--artifact-profile", choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"], default="PRD_ONLY")
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--generation-contract", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    prd = args.prd.resolve()
    if not prd.exists():
        raise SystemExit(f"PRD not found: {prd}")
    text = prd.read_text(encoding="utf-8", errors="replace")
    ref = str(prd)
    contracts = extract_contracts(text, prd)
    units: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    fr_units: dict[str, dict[str, Any]] = {}
    for match in FR_RE.finditer(text):
        fr_id = match.group(2)
        title = clean(match.group(3))
        content = block_for(text, match)
        sections = split_subsections(content)
        statement = sections.get("产品逻辑") or sections.get("需求说明") or clean(content)[:800]
        unit = {
            "unitId": fr_id,
            "kind": "FEATURE_SLICE",
            "title": title,
            "statement": statement,
            "sourceRef": ref,
            "authority": "PRD",
            "frIds": [fr_id],
            "acIds": [],
            "dependencies": [],
            "sections": sections,
            "fields": {},
            "content": content,
        }
        units.append(unit)
        fr_units[fr_id] = unit

    ac_units: dict[str, dict[str, Any]] = {}
    for match in AC_RE.finditer(text):
        ac_id = match.group(2)
        title = clean(match.group(3))
        content = block_for(text, match)
        fields = parse_fields(content)
        linked_fr = expand_id_ranges(fields.get("关联功能", ""))
        statement = fields.get("THEN") or clean(content)[:800]
        unit = {
            "unitId": ac_id,
            "kind": "ACCEPTANCE_CRITERION",
            "title": title,
            "statement": statement,
            "sourceRef": ref,
            "authority": "PRD",
            "frIds": linked_fr,
            "acIds": [ac_id],
            "dependencies": linked_fr,
            "sections": {},
            "fields": fields,
            "content": content,
        }
        units.append(unit)
        ac_units[ac_id] = unit
        for fr_id in linked_fr:
            add_edge(edges, fr_id, ac_id, "VERIFIED_BY", [ref])
            add_edge(edges, ac_id, fr_id, "VERIFIES", [ref])

    goal_section = section_by_title(text, r"目标列表") or section_by_title(text, r"总体目标")
    goal_text_block = goal_section[1] if goal_section else ""
    for goal in GOAL_ROW_RE.finditer(goal_text_block):
        goal_id, goal_text, function_refs = goal.groups()
        fr_ids = [item for item in expand_id_ranges(function_refs) if item.startswith("FR-")]
        units.append({
            "unitId": f"JOURNEY-{goal_id}",
            "kind": "JOURNEY",
            "title": goal_id,
            "statement": clean(goal_text),
            "sourceRef": ref,
            "authority": "PRD",
            "frIds": fr_ids,
            "acIds": [],
            "dependencies": fr_ids,
            "sections": {},
            "fields": {},
            "content": clean(goal_text),
        })
        for fr_id in fr_ids:
            add_edge(edges, f"JOURNEY-{goal_id}", fr_id, "COVERS", [ref])

    manifest_elements: list[dict[str, Any]] = []
    if args.manifest and args.manifest.exists():
        manifest_path = args.manifest.resolve()
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_elements = manifest_data.get("elements", [])
        except Exception as exc:
            raise SystemExit(f"invalid manifest: {exc}")
        for element in manifest_elements:
            ui_id = element.get("uiElementId")
            if not ui_id:
                continue
            fr_ids = element.get("frIds", [])
            ac_ids = element.get("acIds", [])
            states = element.get("states", [])
            permissions = element.get("permissions", [])
            unit = {
                "unitId": ui_id,
                "kind": "INTERACTION_CONTRACT",
                "title": element.get("visibleLabel", ui_id),
                "statement": clean(f"action={element.get('action', '')} states={','.join(states)} permissions={','.join(permissions)}"),
                "sourceRef": str(manifest_path),
                "authority": "PROTOTYPE",
                "frIds": fr_ids,
                "acIds": ac_ids,
                "dependencies": fr_ids + ac_ids,
                "sections": {"states": json.dumps(states, ensure_ascii=False), "permissions": json.dumps(permissions, ensure_ascii=False)},
                "fields": {"action": element.get("action", ""), "visibleLabel": element.get("visibleLabel", "")},
                "content": json.dumps(element, ensure_ascii=False),
            }
            units.append(unit)
            for fr_id in fr_ids:
                add_edge(edges, ui_id, fr_id, "BINDS_UI", [str(manifest_path)])
            for ac_id in ac_ids:
                add_edge(edges, ui_id, ac_id, "BINDS_UI", [str(manifest_path)])

    global_ids = {item["contractId"] for item in contracts}
    for unit in units:
        if unit["kind"] != "FEATURE_SLICE":
            continue
        dependencies = set(unit["dependencies"])
        if "GC-SCOPE" in global_ids:
            dependencies.add("GC-SCOPE")
            add_edge(edges, unit["unitId"], "GC-SCOPE", "DEPENDS_ON", [ref])
        if "GC-GOALS" in global_ids:
            dependencies.add("GC-GOALS")
            add_edge(edges, unit["unitId"], "GC-GOALS", "DEPENDS_ON", [ref])
        if re.search(r"权限|角色|可见|隐藏|禁用|无权限|访问", unit["content"], re.I) and "GC-PERMISSIONS" in global_ids:
            dependencies.add("GC-PERMISSIONS")
            add_edge(edges, unit["unitId"], "GC-PERMISSIONS", "DEPENDS_ON", [ref])
        if re.search(r"状态|成功|失败|空态|加载|处理中|禁用", unit["content"], re.I) and "GC-STATE-MODEL" in global_ids:
            dependencies.add("GC-STATE-MODEL")
            add_edge(edges, unit["unitId"], "GC-STATE-MODEL", "DEPENDS_ON", [ref])
        if re.search(r"既有|沿用|回归", unit["content"], re.I) and "GC-CAPABILITY-BASELINE" in global_ids:
            dependencies.add("GC-CAPABILITY-BASELINE")
            add_edge(edges, unit["unitId"], "GC-CAPABILITY-BASELINE", "DEPENDS_ON", [ref])
        unit["dependencies"] = sorted(dependencies)

    source: dict[str, Any] = {"prdPath": ref, "prdSha256": sha256(prd)}
    if args.prototype and args.prototype.exists():
        prototype = args.prototype.resolve()
        source["prototypePath"] = str(prototype)
        source["prototypeSha256"] = sha256(prototype)
    if args.manifest and args.manifest.exists():
        manifest = args.manifest.resolve()
        source["manifestPath"] = str(manifest)
        source["manifestSha256"] = sha256(manifest)

    metrics = {
        "globalContracts": len(contracts),
        "featureSlices": sum(1 for unit in units if unit["kind"] == "FEATURE_SLICE"),
        "acceptanceCriteria": sum(1 for unit in units if unit["kind"] == "ACCEPTANCE_CRITERION"),
        "interactionContracts": sum(1 for unit in units if unit["kind"] == "INTERACTION_CONTRACT"),
        "journeys": sum(1 for unit in units if unit["kind"] == "JOURNEY"),
        "edges": len(edges),
    }
    payload = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "targetRevision": args.revision,
        "artifactProfile": args.artifact_profile,
        **({"generationContractPath": str(args.generation_contract.resolve())} if args.generation_contract and args.generation_contract.exists() else {}),
        "source": source,
        "globalContracts": contracts,
        "units": units,
        "edges": edges,
        "findings": [],
        "metrics": metrics,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "BUILT", **metrics, "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
