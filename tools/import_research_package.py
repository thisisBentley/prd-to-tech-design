#!/usr/bin/env python3
"""Verify and import a frozen Research Evidence Package into a Delivery run."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from validate_agent_contracts import validate_decision, validate_research_record


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    package = args.package.resolve()
    run_root = args.run_root.resolve()
    manifest_path = package / "manifest.json"
    errors: list[str] = []
    manifest: dict[str, Any] = {}
    try:
        manifest = load(manifest_path)
        required = {"schemaVersion", "requirementKey", "workflowId", "classification", "generatedAt", "files"}
        missing = sorted(required - set(manifest))
        if missing:
            errors.append(f"manifest missing: {missing}")
    except Exception as exc:
        errors.append(f"invalid manifest: {exc}")
    package_id = hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:16] if manifest_path.exists() else "invalid"
    imported_path = run_root / ".agents" / "research" / "imported" / package_id
    if package_id != "invalid" and imported_path.exists() and not args.force:
        errors.append(f"import destination already exists: {imported_path}")
    verified_files: list[str] = []
    if manifest and not errors:
        for index, item in enumerate(manifest.get("files", [])):
            rel = str(item.get("path", ""))
            if not safe_relative(rel):
                errors.append(f"files[{index}] unsafe path: {rel}")
                continue
            source = package / rel
            if not source.is_file():
                errors.append(f"files[{index}] missing: {rel}")
                continue
            if source.stat().st_size != item.get("size"):
                errors.append(f"files[{index}] size mismatch: {rel}")
            if digest(source) != item.get("sha256"):
                errors.append(f"files[{index}] hash mismatch: {rel}")
            verified_files.append(rel)
    if not errors:
        if imported_path.exists():
            shutil.rmtree(imported_path)
        imported_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package, imported_path)
        # Remove stale files that were not part of the verified manifest.
        allowed = set(verified_files) | {"manifest.json"}
        for path in sorted(imported_path.rglob("*"), reverse=True):
            if path.is_file() and path.relative_to(imported_path).as_posix() not in allowed:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()

    research_paths = sorted((imported_path / "research-records").glob("*.json")) if imported_path.exists() else []
    decision_paths = sorted((imported_path / "decision-cards").glob("*.json")) if imported_path.exists() else []
    records: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for path in research_paths:
        try:
            data = load(path)
            errors.extend(validate_research_record(data, str(path)))
            if manifest and data.get("workflowId") != manifest.get("workflowId"):
                errors.append(f"{path}: workflowId mismatch")
            records.append(data)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    for path in decision_paths:
        try:
            data = load(path)
            errors.extend(validate_decision(data, str(path)))
            if manifest and data.get("workflowId") != manifest.get("workflowId"):
                errors.append(f"{path}: workflowId mismatch")
            research_ref = Path(data.get("researchRecordPath", ""))
            if not research_ref.is_absolute():
                research_ref = path.parent / research_ref
            research_ref = research_ref.resolve()
            if not research_ref.exists():
                errors.append(f"{path}: research record not found: {research_ref}")
            else:
                linked = load(research_ref)
                if linked.get("verdict") != "NEEDS_BUSINESS_DECISION" or linked.get("decisionRequired") is not True:
                    errors.append(f"{path}: Decision Card must reference NEEDS_BUSINESS_DECISION research")
            decisions.append(data)
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    context_dir = run_root / ".agents" / "context"
    decisions_dir = run_root / ".agents" / "decisions"
    context_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    technical_gaps = [
        {
            "researchId": record.get("researchId"),
            "clue": record.get("clue"),
            "nextAction": record.get("nextAction"),
            "evidenceRefs": record.get("evidenceRefs", []),
        }
        for record in records
        if record.get("resolutionOwner") == "TECH" and record.get("verdict") in {"FACT_CONFLICT", "NO_EVIDENCE"}
    ]
    if not errors:
        capability_registry = imported_path / "research-capabilities.json"
        if capability_registry.exists():
            shutil.copyfile(capability_registry, context_dir / "research-capabilities.json")
        technical_path = context_dir / "technical-gaps.json"
        technical_path.write_text(json.dumps({"schemaVersion": 1, "workflowId": manifest["workflowId"], "gaps": technical_gaps}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for source in decision_paths:
            shutil.copyfile(source, decisions_dir / source.name)
        state_path = run_root / ".agents" / "orchestration.json"
        if state_path.exists():
            state = load(state_path)
            registered = state.setdefault("researchRecords", [])
            for source in research_paths:
                rel = str(source.relative_to(run_root).as_posix())
                if rel not in registered:
                    registered.append(rel)
            decision_state = state.setdefault("decisions", [])
            for source in decision_paths:
                rel = str((decisions_dir / source.name).relative_to(run_root).as_posix())
                if rel not in decision_state:
                    decision_state.append(rel)
            state["updatedAt"] = datetime.now(timezone.utc).isoformat()
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index_path = run_root / ".agents" / "research" / "imported-packages.json"
        index = {"schemaVersion": 1, "packages": []}
        if index_path.exists():
            try:
                index = load(index_path)
            except Exception:
                pass
        entry = {"packageId": package_id, "path": str(imported_path), "classification": manifest.get("classification"), "requirementKey": manifest.get("requirementKey"), "records": len(records), "decisions": len(decisions), "technicalGaps": len(technical_gaps)}
        index["packages"] = [item for item in index.get("packages", []) if item.get("packageId") != package_id] + [entry]
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "BLOCKED",
        "packagePath": str(package),
        "importedPath": str(imported_path),
        "classification": manifest.get("classification", "SYNTHETIC"),
        "researchRecords": len(records),
        "decisionCards": len(decisions),
        "technicalGaps": len(technical_gaps),
        "errors": errors,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "records": len(records), "decisions": len(decisions), "technicalGaps": len(technical_gaps), "errors": len(errors), "out": str(args.out)}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
