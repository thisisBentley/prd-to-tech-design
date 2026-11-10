#!/usr/bin/env python3
"""Validate and freeze a Research Evidence Package with a deterministic manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_agent_contracts import validate_decision, validate_research_record


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--requirement-key", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--classification", choices=["SYNTHETIC", "MIXED", "REAL"], default="SYNTHETIC")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    record_paths = sorted((root / "research-records").glob("*.json")) if (root / "research-records").exists() else []
    decision_paths = sorted((root / "decision-cards").glob("*.json")) if (root / "decision-cards").exists() else []
    if not record_paths and not decisions:
        errors.append("package requires at least one Research Record or Decision Card")
    for path in record_paths:
        try:
            data = load(path)
            errors.extend(validate_research_record(data, str(path)))
            if data.get("workflowId") != args.workflow_id:
                errors.append(f"{path}: workflowId mismatch")
            records.append(data)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    for path in decision_paths:
        try:
            data = load(path)
            errors.extend(validate_decision(data, str(path)))
            if data.get("workflowId") != args.workflow_id:
                errors.append(f"{path}: workflowId mismatch")
            research_path = Path(data.get("researchRecordPath", ""))
            if not research_path.is_absolute():
                research_path = path.parent / research_path
            research_path = research_path.resolve()
            if not research_path.exists():
                errors.append(f"{path}: research record not found: {research_path}")
            else:
                linked = load(research_path)
                if linked.get("verdict") != "NEEDS_BUSINESS_DECISION" or linked.get("decisionRequired") is not True:
                    errors.append(f"{path}: Decision Card must reference NEEDS_BUSINESS_DECISION research")
            decisions.append(data)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    capability_path = root / "research-capabilities.json"
    if capability_path.exists():
        try:
            capabilities = load(capability_path)
            if capabilities.get("schemaVersion") != 1 or not isinstance(capabilities.get("sources"), list):
                errors.append(f"{capability_path}: invalid capability registry")
        except Exception as exc:
            errors.append(f"{capability_path}: {exc}")
    manifest_path = args.out.resolve() if args.out else root / "manifest.json"
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() == manifest_path:
            continue
        files.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": digest(path),
            "size": path.stat().st_size,
        })
    manifest = {
        "schemaVersion": 1,
        "requirementKey": args.requirement_key,
        "workflowId": args.workflow_id,
        "classification": args.classification,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    if errors:
        output = {"schemaVersion": 1, "status": "BLOCKED", "errors": errors, "manifestPath": str(manifest_path)}
    else:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output = {
            "schemaVersion": 1,
            "status": "FROZEN",
            "manifestPath": str(manifest_path),
            "files": len(files),
            "researchRecords": len(records),
            "decisionCards": len(decisions),
        }
    print(json.dumps(output, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
