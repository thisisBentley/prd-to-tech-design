#!/usr/bin/env python3
"""Validate structural and production-candidate quality of Delivery artifacts."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")
BR_RE = re.compile(r"\bBR-[0-9]{3}\b")
PLACEHOLDER_PATTERNS = [
    r"FR-[0-9]{3}\s+interaction",
    r"\bbounded interaction\b",
    r"as defined by PRD",
    r"UNSPECIFIED role",
    r"precondition defined by PRD",
    r"All supplied functional requirements are implemented and verifiable",
    r"TRACEABILITY_PLACEHOLDER",
    r"TODO",
    r"TBD",
]
REQUIRED_PRD_SECTIONS = ["functional requirements", "acceptance criteria", "permissions", "states", "non-goals"]
PRODUCTION_PRD_SECTIONS = ["exceptions", "recovery"]
REQUIRED_OVERVIEW_TABS = ["方案摘要", "背景与现状", "目标与范围", "功能与规则", "流程与状态", "验收与风险"]
REQUIRED_JIRA_SECTIONS = ["背景", "现状", "目标", "功能点"]


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.exists() else None


def visible_text(path: Path) -> str:
    return re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="replace")).replace("&nbsp;", " ")


def check(check_id: str, passed: bool, observed: Any, expected: Any, evidence: list[str]) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
        "evidenceRefs": [item for item in evidence if item],
    }


def validate(prd: Path, profile: str, producer_mode: str, prototype: Path | None = None, manifest_path: Path | None = None, overview: Path | None = None, jira: Path | None = None, prd_producer_mode: str | None = None, runtime_path: Path | None = None) -> dict[str, Any]:
    prd_producer_mode = prd_producer_mode or producer_mode
    prd_text = prd.read_text(encoding="utf-8")
    prd_lower = prd_text.lower()
    frs = sorted(set(FR_RE.findall(prd_text)))
    acs = sorted(set(AC_RE.findall(prd_text)))
    brs = sorted(set(BR_RE.findall(prd_text)))
    checks: list[dict[str, Any]] = []
    quality_defects: list[str] = []
    evidence = [str(prd.resolve())]
    checks.append(check("PRD.PRESENT", prd.exists() and bool(prd_text.strip()), {"bytes": len(prd_text)}, "non-empty PRD", evidence))
    checks.append(check("PRD.IDENTIFIERS", bool(frs) and bool(acs), {"FR": frs, "AC": acs, "BR": brs}, "at least one FR and AC", evidence))
    missing_sections = [section for section in REQUIRED_PRD_SECTIONS if section not in prd_lower]
    checks.append(check("PRD.STRUCTURE", not missing_sections, {"missing": missing_sections}, "core PRD sections present", evidence))
    missing_production_sections = [section for section in PRODUCTION_PRD_SECTIONS if section not in prd_lower]
    if missing_production_sections:
        quality_defects.append("PRD missing production sections: " + ", ".join(missing_production_sections))
    traced_frs: set[str] = set()
    for ac in acs:
        match = re.search(rf"\b{re.escape(ac)}\b", prd_text)
        if match:
            window = prd_text[max(0, match.start() - 900): min(len(prd_text), match.end() + 1400)]
            traced_frs.update(FR_RE.findall(window))
    untraced_frs = sorted(set(frs) - traced_frs)
    if untraced_frs:
        quality_defects.append("PRD FRs not traceably referenced by AC: " + ", ".join(untraced_frs))
    placeholder_hits = [pattern for pattern in PLACEHOLDER_PATTERNS if re.search(pattern, prd_text, re.IGNORECASE)]
    if placeholder_hits:
        quality_defects.append("PRD contains placeholder patterns: " + ", ".join(placeholder_hits))

    prototype_text = ""
    if profile in {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}:
        prototype_text = prototype.read_text(encoding="utf-8", errors="replace") if prototype and prototype.exists() else ""
        checks.append(check("PROTOTYPE.PRESENT", bool(prototype_text), str(prototype or ""), "Prototype exists for this profile", [str(prototype or ""), str(prd.resolve())]))
        elements = re.findall(r"<[^>]*data-ai-id=\"([^\"]+)\"[^>]*>", prototype_text, re.IGNORECASE)
        checks.append(check("PROTOTYPE.ELEMENTS", bool(elements), elements, "at least one bound data-ai-id", [str(prototype or "")]))
        bound_frs = set()
        bound_acs = set()
        for tag in re.findall(r"<[^>]*data-ai-id=\"[^\"]+\"[^>]*>", prototype_text, re.IGNORECASE):
            bound_frs.update(re.findall(r'data-ai-fr="([^"]+)"', tag))
            bound_acs.update(re.findall(r'data-ai-ac="([^"]+)"', tag))
        missing_prototype_frs = sorted(set(frs) - bound_frs)
        missing_prototype_acs = sorted(set(acs) - bound_acs)
        checks.append(check("PROTOTYPE.FR_COVERAGE", not missing_prototype_frs, missing_prototype_frs, "every PRD FR is bound", [str(prototype or ""), str(prd.resolve())]))
        checks.append(check("PROTOTYPE.AC_COVERAGE", not missing_prototype_acs, missing_prototype_acs, "every PRD AC is bound", [str(prototype or ""), str(prd.resolve())]))
        manifest = load(manifest_path, {}) if manifest_path else {}
        checks.append(check("PROTOTYPE.MANIFEST", bool(manifest.get("elements")), len(manifest.get("elements", [])), "manifest with elements", [str(manifest_path or "")]))
        prototype_placeholders = [pattern for pattern in PLACEHOLDER_PATTERNS if re.search(pattern, prototype_text, re.IGNORECASE)]
        if prototype_placeholders:
            quality_defects.append("Prototype contains placeholder patterns: " + ", ".join(prototype_placeholders))
        if missing_prototype_frs or missing_prototype_acs:
            quality_defects.append("Prototype does not bind every PRD FR/AC")
    else:
        checks.append(check("PROTOTYPE.PRESENT", True, "not applicable", "PRD_ONLY profile", [str(prd.resolve())]))

    if overview and overview.exists():
        overview_text = overview.read_text(encoding="utf-8", errors="replace")
        source_hash = digest(prd)
        checks.append(check("OVERVIEW.PRESENT", True, str(overview), "Overview exists", [str(overview.resolve())]))
        checks.append(check("OVERVIEW.SOURCE_HASH", f"{source_hash}" in overview_text, {"sourceHash": source_hash}, "Overview embeds current PRD hash", [str(overview.resolve()), str(prd.resolve())]))
        missing_tabs = [tab for tab in REQUIRED_OVERVIEW_TABS if tab not in visible_text(overview)]
        checks.append(check("OVERVIEW.TABS", not missing_tabs, {"missing": missing_tabs}, "six required review tabs present", [str(overview.resolve())]))
        if missing_tabs:
            quality_defects.append("Overview missing production tabs: " + ", ".join(missing_tabs))
        overview_frs = set(FR_RE.findall(visible_text(overview)))
        missing_overview_frs = sorted(set(frs) - overview_frs)
        if missing_overview_frs:
            quality_defects.append("Overview omits PRD FRs: " + ", ".join(missing_overview_frs))
    else:
        checks.append(check("OVERVIEW.PRESENT", False, str(overview or ""), "Overview exists", [str(prd.resolve())]))

    if jira and jira.exists():
        jira_text = jira.read_text(encoding="utf-8", errors="replace")
        source_hash = digest(prd)
        checks.append(check("JIRA.PRESENT", True, str(jira), "Jira Description exists", [str(jira.resolve())]))
        checks.append(check("JIRA.SOURCE_HASH", bool(source_hash and source_hash in jira_text), {"sourceHash": source_hash}, "projection embeds current PRD hash", [str(jira.resolve()), str(prd.resolve())]))
        missing_jira_sections = [section for section in REQUIRED_JIRA_SECTIONS if section not in jira_text]
        checks.append(check("JIRA.SECTIONS", not missing_jira_sections, {"missing": missing_jira_sections}, "four required sections present", [str(jira.resolve())]))
        missing_jira_frs = sorted(set(frs) - set(FR_RE.findall(jira_text)))
        checks.append(check("JIRA.FR_COVERAGE", not missing_jira_frs, missing_jira_frs, "every PRD FR appears in functional points", [str(jira.resolve())]))
        if missing_jira_sections or missing_jira_frs:
            quality_defects.append("Jira Description is incomplete")
    else:
        checks.append(check("JIRA.PRESENT", False, str(jira or ""), "Jira Description exists", [str(prd.resolve())]))

    if prd_producer_mode == "deterministic" or prd_producer_mode == "unknown":
        quality_defects.append("PRD producer is not proven semantic/provided and is baseline-only")
    if producer_mode == "deterministic":
        quality_defects.append("Deterministic downstream projection mode is baseline-only and cannot be a production candidate")
    runtime = load(runtime_path, {}) if runtime_path else {}
    if profile in {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}:
        runtime_level = runtime.get("runtimeEvidenceLevel", "STATIC_CONTRACT")
        runtime_ok = runtime.get("status") == "PASS" and runtime_level == "REAL_BROWSER" and not runtime.get("consoleErrors") and not runtime.get("pageErrors") and not runtime.get("requestFailures")
        checks.append(check("RUNTIME.REAL_BROWSER", runtime_ok, {"status": runtime.get("status"), "evidenceLevel": runtime_level}, "real browser evidence with zero runtime errors", [str(runtime_path or "")]))
        if not runtime_ok:
            quality_defects.append("Prototype runtime evidence is not REAL_BROWSER or contains runtime errors")
    structural_failed = [item["checkId"] for item in checks if item["status"] == "failed" and item["checkId"] in {
        "PRD.PRESENT", "PRD.IDENTIFIERS", "PRD.STRUCTURE", "PROTOTYPE.PRESENT", "PROTOTYPE.ELEMENTS", "PROTOTYPE.MANIFEST",
        "OVERVIEW.PRESENT", "JIRA.PRESENT", "JIRA.SECTIONS",
    }]
    production_candidate = not structural_failed and not quality_defects and producer_mode in {"provided", "semantic"} and prd_producer_mode in {"provided", "semantic"}
    if structural_failed:
        status = "BLOCKED"
        quality_level = "BLOCKED"
    elif production_candidate:
        status = "PASS"
        quality_level = "PRODUCTION_CANDIDATE"
    else:
        status = "PASS"
        quality_level = "BASELINE_ONLY"
    artifact_hashes = {}
    for kind, path in (("prd", prd), ("prototype", prototype), ("manifest", manifest_path), ("overview", overview), ("jira", jira)):
        value = digest(path)
        if value:
            artifact_hashes[kind] = value
    return {
        "schemaVersion": 1,
        "status": status,
        "qualityLevel": quality_level,
        "productionCandidate": production_candidate,
        "artifactProfile": profile,
        "producerMode": producer_mode,
        "prdProducerMode": prd_producer_mode,
        "downstreamProducerMode": producer_mode,
        "checks": checks,
        "qualityDefects": quality_defects,
        "blockingCount": len(structural_failed),
        "artifactHashes": artifact_hashes,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--artifact-profile", required=True, choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"])
    parser.add_argument("--producer-mode", choices=["deterministic", "provided", "semantic"], default="deterministic", help="Downstream Prototype/Overview/Jira producer mode.")
    parser.add_argument("--prd-producer-mode", choices=["deterministic", "provided", "semantic", "unknown"])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--jira", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.prd, args.artifact_profile, args.producer_mode, args.prototype, args.manifest, args.overview, args.jira, args.prd_producer_mode, args.runtime)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "qualityLevel": result["qualityLevel"], "productionCandidate": result["productionCandidate"], "defects": len(result["qualityDefects"]), "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
