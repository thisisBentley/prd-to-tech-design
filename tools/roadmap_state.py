#!/usr/bin/env python3
"""Build and validate a deterministic cross-source Roadmap state snapshot."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load as schema_load, validate as schema_validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


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


def validate_schema_value(value: Any, schema_name: str = "roadmap-state.schema.json") -> list[str]:
    schema = schema_load(SCHEMA_DIR / schema_name)
    return schema_validate(value, schema, schema)


def parse_current_iteration(text: str, source_name: str) -> int:
    match = re.search(r"^- 当前迭代：(\d+)\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"{source_name}: current iteration marker not found")
    return int(match.group(1))


def parse_roadmap_milestone(text: str) -> str:
    match = re.search(r"^- 当前主线：\*\*(M[0-9A-Za-z.\-]+)", text, re.MULTILINE)
    if not match:
        raise ValueError("roadmap: current milestone marker not found")
    return match.group(1)


def parse_dataset_training_status(dataset: dict[str, Any]) -> str:
    remediation = dataset.get("trainingRemediation") or {}
    return str(remediation.get("baselineStatus") or remediation.get("baselineB2ExecutionStatus") or "UNKNOWN")


def build_state(
    roadmap_path: Path,
    changelog_path: Path,
    version_manifest_path: Path,
    dataset_status_path: Path,
    expected_milestone: str,
) -> dict[str, Any]:
    roadmap_path = roadmap_path.resolve()
    changelog_path = changelog_path.resolve()
    version_manifest_path = version_manifest_path.resolve()
    dataset_status_path = dataset_status_path.resolve()
    roadmap_text = roadmap_path.read_text(encoding="utf-8")
    changelog_text = changelog_path.read_text(encoding="utf-8")
    manifest = load(version_manifest_path)
    dataset = load(dataset_status_path)
    current = manifest.get("currentMilestone") or {}
    latest = dataset.get("latestMilestone") or {}
    checks: list[dict[str, Any]] = []
    drift: list[str] = []

    def check(check_id: str, observed: Any, expected: Any) -> None:
        ok = observed == expected
        checks.append({"checkId": check_id, "status": "passed" if ok else "failed", "observed": observed, "expected": expected})
        if not ok:
            drift.append(f"{check_id}: observed={observed!r}, expected={expected!r}")

    roadmap_iteration = parse_current_iteration(roadmap_text, "roadmap")
    changelog_iteration = parse_current_iteration(changelog_text, "changelog")
    skill_version = str((manifest.get("localSkill") or {}).get("version", "UNKNOWN"))
    baseline_id = str(manifest.get("baselineId", "UNKNOWN"))
    current_milestone = str(current.get("id", "UNKNOWN"))
    roadmap_milestone = parse_roadmap_milestone(roadmap_text)
    dataset_milestone = str(latest.get("id", "UNKNOWN"))
    training_baseline_status = parse_dataset_training_status(dataset)

    check("STATE.ITERATION", changelog_iteration, roadmap_iteration)
    check("STATE.MILESTONE", current_milestone, expected_milestone)
    check("STATE.ROADMAP_MILESTONE", roadmap_milestone, expected_milestone)
    check("STATE.DATASET_MILESTONE", dataset_milestone, expected_milestone)
    check("STATE.SKILL_VERSION", skill_version, str(manifest.get("localSkill", {}).get("version", "UNKNOWN")))
    check("STATE.BASELINE_ID", baseline_id, str(manifest.get("baselineId", "UNKNOWN")))
    check("STATE.TRAINING_BASELINE", training_baseline_status != "UNKNOWN", True)

    state = {
        "schemaVersion": 1,
        "generatedAt": now(),
        "sources": {
            "roadmap": {"path": str(roadmap_path), "sha256": sha256_file(roadmap_path)},
            "changelog": {"path": str(changelog_path), "sha256": sha256_file(changelog_path)},
            "versionManifest": {"path": str(version_manifest_path), "sha256": sha256_file(version_manifest_path)},
            "datasetStatus": {"path": str(dataset_status_path), "sha256": sha256_file(dataset_status_path)},
        },
        "canonical": {
            "roadmapIteration": roadmap_iteration,
            "changelogIteration": changelog_iteration,
            "skillVersion": skill_version,
            "baselineId": baseline_id,
            "currentMilestone": current_milestone,
            "roadmapMilestone": roadmap_milestone,
            "datasetMilestone": dataset_milestone,
            "trainingBaselineStatus": training_baseline_status,
        },
        "checks": checks,
        "status": "PASS" if not drift else "FAIL",
        "drift": drift,
    }
    errors = validate_schema_value(state)
    if errors:
        raise ValueError("; ".join(errors))
    return state


def validate_state(snapshot: dict[str, Any], rebuilt: dict[str, Any]) -> list[str]:
    errors = validate_schema_value(snapshot)
    if errors:
        return errors
    if snapshot.get("canonical") != rebuilt.get("canonical"):
        errors.append("snapshot canonical state is stale")
    for key, source in (snapshot.get("sources") or {}).items():
        current = (rebuilt.get("sources") or {}).get(key) or {}
        if source.get("sha256") != current.get("sha256"):
            errors.append(f"source drift: {key}")
    if rebuilt.get("status") != "PASS":
        errors.extend(rebuilt.get("drift", []))
    return errors
