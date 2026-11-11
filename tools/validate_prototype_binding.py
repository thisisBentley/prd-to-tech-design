#!/usr/bin/env python3
"""Validate stable PRD/Prototype/AC bindings in a delivery bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

TAG_RE = re.compile(r"<[^>]*\bdata-ai-id=[\"']([^\"']+)[\"'][^>]*>", re.I)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attr(tag: str, name: str) -> list[str]:
    pattern = r"\b" + re.escape(name) + r"\s*=\s*[\"']([^\"']*)[\"']"
    match = re.search(pattern, tag, re.I)
    return re.split(r"[, ]+", match.group(1).strip()) if match and match.group(1).strip() else []


def validate(prototype: Path, manifest_path: Path, prd: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    evidence = [str(prototype), str(manifest_path)]

    def check(check_id: str, passed: bool, observed: Any, expected: str) -> None:
        checks.append({"checkId": check_id, "status": "passed" if passed else "failed", "observed": observed, "expected": expected, "evidenceRefs": evidence})

    check("BINDING.PROTOTYPE_EXISTS", prototype.is_file(), str(prototype), "Prototype file exists")
    check("BINDING.MANIFEST_EXISTS", manifest_path.is_file(), str(manifest_path), "Prototype Manifest exists")
    if not prototype.is_file() or not manifest_path.is_file():
        return {"schemaVersion": 1, "status": "FAIL", "checks": checks, "findings": errors, "warnings": warnings}

    try:
        manifest = load(manifest_path)
    except Exception as exc:
        errors.append(f"invalid manifest JSON: {exc}")
        check("BINDING.MANIFEST_JSON", False, str(exc), "Manifest is valid JSON")
        manifest = {}

    elements = manifest.get("elements") or []
    check("BINDING.MANIFEST_ELEMENTS", bool(elements), len(elements), "Manifest declares at least one UI element")
    actual_hash = digest(prototype)
    check("BINDING.PROTOTYPE_HASH", manifest.get("prototypeHash") == actual_hash, {"manifest": manifest.get("prototypeHash"), "actual": actual_hash}, "Manifest prototypeHash matches Prototype")

    html = prototype.read_text(encoding="utf-8", errors="replace")
    tags = {match.group(1): match.group(0) for match in TAG_RE.finditer(html)}
    manifest_ids = {item.get("uiElementId") for item in elements if item.get("uiElementId")}
    check("BINDING.DATA_AI_IDS", bool(tags), sorted(tags), "Prototype contains data-ai-id attributes")
    check("BINDING.MANIFEST_HTML_IDS", manifest_ids == set(tags), {"manifestOnly": sorted(manifest_ids - set(tags)), "htmlOnly": sorted(set(tags) - manifest_ids)}, "Manifest UI IDs equal Prototype data-ai-id IDs")

    binding_errors: list[dict[str, Any]] = []
    for element in elements:
        ui_id = element.get("uiElementId", "")
        tag = tags.get(ui_id, "")
        if not tag:
            continue
        html_fr = attr(tag, "data-ai-fr")
        html_ac = attr(tag, "data-ai-ac")
        expected_fr = element.get("frIds", [])
        expected_ac = element.get("acIds", [])
        if html_fr != expected_fr or html_ac != expected_ac:
            binding_errors.append({"uiElementId": ui_id, "htmlFr": html_fr, "htmlAc": html_ac, "manifestFr": expected_fr, "manifestAc": expected_ac})
        if not html_ac:
            binding_errors.append({"uiElementId": ui_id, "error": "missing data-ai-ac"})
    check("BINDING.HTML_FR_AC", not binding_errors, binding_errors, "Every Manifest element carries matching data-ai-fr/data-ai-ac in HTML")

    missing_states = [item.get("uiElementId") for item in elements if not item.get("states")]
    check("BINDING.STATES", not missing_states, missing_states, "Every UI element declares meaningful states")

    if prd and prd.is_file():
        text = prd.read_text(encoding="utf-8", errors="replace")
        prd_fr = set(re.findall(r"FR-\d{3}", text))
        prd_ac = set(re.findall(r"AC-\d{3}", text))
        manifest_fr = {value for item in elements for value in item.get("frIds", [])}
        manifest_ac = {value for item in elements for value in item.get("acIds", [])}
        check("BINDING.PRD_FR_COVERAGE", prd_fr <= manifest_fr, {"missing": sorted(prd_fr - manifest_fr)}, "Every PRD FR is bound to a UI element")
        check("BINDING.PRD_AC_COVERAGE", prd_ac <= manifest_ac, {"missing": sorted(prd_ac - manifest_ac)}, "Every PRD AC is bound to a UI element")
        unknown_fr = sorted(manifest_fr - prd_fr)
        unknown_ac = sorted(manifest_ac - prd_ac)
        check("BINDING.MANIFEST_PRD_REFERENCES", not unknown_fr and not unknown_ac, {"unknownFr": unknown_fr, "unknownAc": unknown_ac}, "Manifest references existing PRD FR/AC IDs")
    else:
        warnings.append("PRD not supplied; FR/AC coverage was not checked")

    failed = [item for item in checks if item["status"] == "failed"]
    return {
        "schemaVersion": 1,
        "status": "FAIL" if failed else "PASS",
        "prototype": str(prototype),
        "prototypeHash": actual_hash,
        "manifest": str(manifest_path),
        "checks": checks,
        "findings": [item["checkId"] for item in failed],
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate(args.prototype.resolve(), args.manifest.resolve(), args.prd.resolve() if args.prd else None)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else json.dumps({"status": result["status"], "findings": result["findings"], "warnings": result["warnings"]}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
