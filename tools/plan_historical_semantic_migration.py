#!/usr/bin/env python3
"""Generate evidence-only migration candidates from a historical delivery package."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import now, validate_schema_value

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
H2_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)

TOPIC_ALIASES = {
    "background": ["需求背景", "背景"],
    "goals": ["需求目标", "目标"],
    "scope": ["本期范围", "范围"],
    "requirements": ["详细需求", "功能需求"],
    "business_rules": ["业务规则", "规则"],
    "states": ["状态"],
    "exceptions": ["异常", "异常与恢复"],
    "acceptance": ["测试验收", "验收标准", "验收"],
    "non_goals": ["非目标", "本期不包含"],
    "permissions": ["权限"],
}
OVERVIEW_ALIASES = {
    "summary": ["方案摘要", "背景与总览"],
    "goal_scope": ["目标与范围"],
    "rules": ["功能与规则"],
    "flow": ["方案与流程", "流程与状态", "原型与交互"],
    "acceptance": ["验收与保障", "验收与风险"],
}
STOPWORDS = {"when", "then", "and", "the", "with", "from", "this", "that", "页面", "用户", "展示", "支持", "正确", "验证"}


def visible(html_text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", html_text))).strip()


def section_bytes(html_text: str, aliases: list[str]) -> int:
    for alias in aliases:
        pattern = rf"<(h[1-6])[^>]*>[^<]*{re.escape(alias)}[^<]*</\1>"
        match = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        level = int(match.group(1)[1])
        end = len(html_text)
        for next_match in H2_RE.finditer(html_text[match.end():]):
            if int(next_match.group(1)) <= level:
                end = match.end() + next_match.start()
                break
        return len(visible(html_text[match.end():end]).encode("utf-8"))
    return 0


def headings(text: str) -> list[tuple[int, str, int, int]]:
    result = []
    for match in HEADING_RE.finditer(text):
        result.append((len(match.group(1)), match.group(2).strip(), match.start(), match.end()))
    return result


def section_for_offset(hs: list[tuple[int, str, int, int]], offset: int) -> str:
    current = ""
    for level, title, start, _ in hs:
        if start <= offset:
            current = title
        else:
            break
    return current


def section_text(text: str, hs: list[tuple[int, str, int, int]], title_fragment: str) -> tuple[str, int]:
    for index, (level, title, _, end) in enumerate(hs):
        if title_fragment.lower() not in title.lower():
            continue
        next_start = len(text)
        for next_level, _, start, _ in hs[index + 1:]:
            if next_level <= level:
                next_start = start
                break
        return text[end:next_start], end
    return "", -1


def tokens(text: str) -> set[str]:
    ascii_tokens = {item.lower() for item in re.findall(r"[A-Za-z][A-Za-z0-9_:-]{2,}", text)}
    chinese_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,6}", text))
    return {item for item in ascii_tokens | chinese_tokens if item.lower() not in STOPWORDS}


def similarity(a: str, b: str) -> float:
    left, right = tokens(a), tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def extract_fr_objects(prd_text: str, hs: list[tuple[int, str, int, int]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for match in FR_RE.finditer(prd_text):
        fr_id = match.group(0)
        if fr_id in seen:
            continue
        seen.add(fr_id)
        line_start = prd_text.rfind("\n", 0, match.start()) + 1
        line_end = prd_text.find("\n", match.end())
        if line_end < 0:
            line_end = len(prd_text)
        line = prd_text[line_start:line_end].strip().lstrip("#-* ").strip()
        title = re.sub(rf"^{re.escape(fr_id)}\s*[：:]\s*", "", line).strip() or fr_id
        heading = section_for_offset(hs, match.start())
        result.append({"frId": fr_id, "title": title[:300], "sourceSection": heading, "evidence": [f"{fr_id}:{line[:240]}"]})
    return sorted(result, key=lambda item: item["frId"])


def extract_ac_objects(prd_text: str, hs: list[tuple[int, str, int, int]], fr_objects: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result = []
    candidate_links = []
    seen = set()
    for match in AC_RE.finditer(prd_text):
        ac_id = match.group(0)
        if ac_id in seen:
            continue
        seen.add(ac_id)
        line_start = prd_text.rfind("\n", 0, match.start()) + 1
        line_end = prd_text.find("\n", match.end())
        if line_end < 0:
            line_end = len(prd_text)
        line = prd_text[line_start:line_end].strip()
        section_title = section_for_offset(hs, match.start())
        table_cells = [cell.strip() for cell in line.strip("|").split("|")]
        explicit_frs = sorted({fr for cell in table_cells for fr in FR_RE.findall(cell)})
        cells_with_fr = [cell for cell in table_cells if FR_RE.search(cell)]
        candidates = explicit_frs[:]
        if not candidates:
            window = prd_text[max(0, match.start() - 300): min(len(prd_text), match.end() + 900)]
            candidates = sorted(set(FR_RE.findall(window)))
            if len(candidates) > 1:
                candidates = []
            elif candidates:
                section_title = "LOCAL_WINDOW:" + section_title
        scored = []
        for fr in fr_objects:
            if fr["frId"] in candidates:
                scored.append((1.0, fr["frId"], "TABLE_CELL" if fr["frId"] in explicit_frs else "LOCAL_SECTION"))
            else:
                score = similarity(line, fr["title"] + " " + fr["sourceSection"])
                if score >= 0.25:
                    scored.append((score, fr["frId"], "TEXT_SIMILARITY"))
        scored.sort(reverse=True)
        if len(scored) > 1 and not explicit_frs:
            top_score = scored[0][0]
            if sum(1 for score, _, _ in scored if score == top_score) > 1:
                scored = []
        candidate_ids = [item[1] for item in scored]
        text = line.strip("| ").strip()
        result.append({"acId": ac_id, "text": text[:500] or ac_id, "sourceSection": section_title, "candidateFrIds": candidate_ids[:3], "evidence": [f"{ac_id}:{text[:300]}"]})
        for _, fr_id, basis in scored[:3]:
            if basis == "TEXT_SIMILARITY":
                candidate_links.append({"acId": ac_id, "frId": fr_id, "confidence": "LOW", "basis": basis, "evidence": [f"{ac_id}:{fr_id}"]})
            else:
                candidate_links.append({"acId": ac_id, "frId": fr_id, "confidence": "MEDIUM", "basis": basis, "evidence": [f"{ac_id}:{fr_id}"]})
    # Explicit references supersede table/local text guesses for the same pair.
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    rank = {"EXPLICIT_REFERENCE": 4, "TABLE_CELL": 3, "LOCAL_SECTION": 2, "TEXT_SIMILARITY": 1}
    for item in candidate_links:
        key = (item["acId"], item["frId"])
        existing = by_pair.get(key)
        if existing is None or rank[item["basis"]] > rank[existing["basis"]]:
            by_pair[key] = item
    links = sorted(by_pair.values(), key=lambda x: (x["acId"], x["frId"]))
    return sorted(result, key=lambda item: item["acId"]), links


def build_plan(sample: dict[str, Any]) -> dict[str, Any]:
    case_id = str(sample["caseId"])
    root = Path(sample["sourceRoot"]).resolve()
    artifacts = {name: Path(value).resolve() if value else None for name, value in sample.get("artifacts", {}).items()}
    if not artifacts.get("prd") or not artifacts["prd"].is_file():
        raise ValueError(f"{case_id}: PRD is missing")
    prd_text = artifacts["prd"].read_text(encoding="utf-8", errors="replace")
    hs = headings(prd_text)
    prd_sections = [title for _, title, _, _ in hs]
    missing_topics = []
    for topic, aliases in TOPIC_ALIASES.items():
        if not any(any(alias.lower() in title.lower() for alias in aliases) for title in prd_sections):
            missing_topics.append(topic)
    fr_objects = extract_fr_objects(prd_text, hs)
    ac_objects, candidate_links = extract_ac_objects(prd_text, hs, fr_objects)
    unresolved = [{"acId": item["acId"], "reason": "No evidence-backed FR candidate found.", "candidateFrIds": item["candidateFrIds"]} for item in ac_objects if not item["candidateFrIds"]]

    prototype_path = artifacts.get("prototype")
    modern_count = legacy_count = mappable = 0
    unmapped_legacy_markers = []
    if prototype_path and prototype_path.is_file():
        phtml = prototype_path.read_text(encoding="utf-8", errors="replace")
        modern_count = len(re.findall(r'data-ai-(?:id|fr|ac)=', phtml, re.IGNORECASE))
        legacy_tags = re.findall(r'<[^>]*data-(?:testid|page-menu-sn|business-zone|metric-key)="[^"]+"[^>]*>', phtml, re.IGNORECASE)
        legacy_count = len(legacy_tags)
        mappable = len(re.findall(r'data-ai-fr="FR-[0-9]{3}"', phtml, re.IGNORECASE)) if modern_count else 0
        for tag in legacy_tags[:50]:
            marker = re.search(r'data-(?:testid|page-menu-sn|business-zone|metric-key)="([^"]+)"', tag, re.IGNORECASE)
            if marker:
                unmapped_legacy_markers.append(marker.group(1)[:120])

    overview = artifacts.get("overview")
    source_ref = source_hash = False
    tabs = {key: 0 for key in OVERVIEW_ALIASES}
    overview_actions = []
    if overview and overview.is_file():
        ohtml = overview.read_text(encoding="utf-8", errors="replace")
        source_ref = bool(re.search(r'name=["\']source-prd["\']', ohtml, re.IGNORECASE))
        source_hash = bool(re.search(r'name=["\']source-prd-sha256["\']', ohtml, re.IGNORECASE))
        tabs = {key: section_bytes(ohtml, aliases) for key, aliases in OVERVIEW_ALIASES.items()}
        if source_ref and not source_hash:
            overview_actions.append("Add current PRD SHA-256 metadata during migration.")
        thin = [key for key, size in tabs.items() if size < 30]
        if thin:
            overview_actions.append("Review and expand migrated Overview sections: " + ", ".join(thin) + ".")
    status = "BLOCKED" if not fr_objects or not ac_objects else ("PARTIAL" if unresolved or missing_topics or not modern_count else "READY_FOR_REVIEW")
    payload = {
        "schemaVersion": 1,
        "caseId": case_id,
        "sourceRoot": str(root),
        "status": status,
        "prd": {"path": str(artifacts["prd"]), "sha256": sha256_file(artifacts["prd"]), "sections": prd_sections, "missingTopics": missing_topics},
        "frObjects": fr_objects,
        "acObjects": ac_objects,
        "candidateLinks": candidate_links,
        "unresolved": unresolved,
        "prototypeBindings": {"modernCount": modern_count, "legacyCount": legacy_count, "mappableModernCount": mappable, "unmappedLegacyMarkers": unmapped_legacy_markers},
        "overviewMigration": {"sourceRefPresent": source_ref, "sourceHashPresent": source_hash, "tabs": tabs, "recommendedActions": overview_actions},
    }
    digest = canonical_hash(payload)
    plan = {"planId": "HIST-MIGRATION-" + digest[:16], **payload, "contentSha256": digest, "createdAt": now()}
    errors = validate_schema_value(plan, "historical-migration-plan.schema.json")
    if errors:
        raise ValueError("invalid historical migration plan: " + "; ".join(errors))
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    spec = load(args.spec.resolve())
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    plans = []
    for sample in spec.get("samples", []):
        try:
            plan = build_plan(sample)
        except Exception as exc:
            plan = {"caseId": sample.get("caseId", "UNKNOWN"), "status": "BLOCKED", "error": str(exc)}
        if "planId" in plan:
            save(out_dir / f"{plan['caseId']}.migration-plan.json", plan)
        plans.append(plan)
    summary = {
        "schemaVersion": 1,
        "caseCount": len(plans),
        "statusCounts": {status: sum(1 for item in plans if item.get("status") == status) for status in ("READY_FOR_REVIEW", "PARTIAL", "BLOCKED")},
        "cases": [{"caseId": item.get("caseId"), "status": item.get("status"), "candidateLinks": len(item.get("candidateLinks", [])), "unresolved": len(item.get("unresolved", [])), "plan": str(out_dir / f"{item.get('caseId')}.migration-plan.json") if item.get("status") != "BLOCKED" or "planId" in item else None} for item in plans],
        "checkedAt": now(),
    }
    save(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
