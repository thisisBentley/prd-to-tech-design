#!/usr/bin/env python3
"""Classify changes between two frozen artifact revisions.

This is a portable quality-core tool. It does not know Jira, external gates or
company-specific statuses. It only decides whether core business artifacts
changed, so evidence-only updates do not restart the full Agent chain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SEMANTIC_NAMES = {
    "PRD_DELIVERY.md", "PRD.md", "requirements.json", "decision-context.json",
    "context-snapshot.json", "capability-matrix.json", "handoff.json",
}
PROJECTION_NAMES = {"Overview.html", "Jira_Description.md", "jira-description.md"}
EVIDENCE_NAMES = {"Gates.md", "Workflow.md", "gate-result.json", "summary.json", "final-seal.json", "candidate-seal.json", "transcript.md", "transcript.log"}
RUNTIME_NAMES = {"runtime-result.json", "runtime.stderr.log", "runtime.stdout.log", "screenshot.png", "runtime.png"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def files(root: Path) -> dict[str, str]:
    if not root.exists():
        raise SystemExit(f"missing revision directory: {root}")
    return {str(p.relative_to(root)): digest(p) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


def basename_class(name: str) -> str:
    base = Path(name).name
    if base in SEMANTIC_NAMES or "PRD" in base or base in {"requirements.json", "decision-context.json"}:
        return "SEMANTIC"
    if base in PROJECTION_NAMES or "Overview" in base or "Jira_Description" in base:
        return "PROJECTION"
    if base in RUNTIME_NAMES or "runtime" in base.lower() or "screenshot" in base.lower():
        return "RUNTIME"
    if base in EVIDENCE_NAMES or "Gate" in base or "Workflow" in base or "transcript" in base.lower() or "seal" in base.lower():
        return "EVIDENCE"
    return "UNKNOWN"


def classify(previous: Path, current: Path, previous_revision: str, current_revision: str) -> dict[str, Any]:
    old, new = files(previous), files(current)
    changed = sorted(set(old) | set(new))
    changed = [name for name in changed if old.get(name) != new.get(name)]
    classes = {name: basename_class(name) for name in changed}
    values = set(classes.values())
    core_changed = bool(values & {"SEMANTIC", "UNKNOWN"})
    if not changed:
        classification, action = "EVIDENCE_ONLY", "DETERMINISTIC_EVIDENCE_RECHECK"
        notes = ["No file hash changed between revisions."]
    elif "UNKNOWN" in values:
        classification, action = "UNKNOWN", "MANUAL_TRIAGE"
        notes = ["A changed file could not be safely classified; default to manual triage."]
    elif core_changed and values - {"SEMANTIC"}:
        classification, action = "MIXED", "FULL_CORE_REVIEW"
        notes = ["Semantic files changed together with projection, evidence or runtime files."]
    elif core_changed:
        classification, action = "SEMANTIC", "FULL_CORE_REVIEW"
        notes = ["At least one semantic/core artifact changed."]
    elif values == {"PROJECTION"}:
        classification, action = "PROJECTION", "PROJECTION_REVIEW"
        notes = ["Only projection artifacts changed; do not restart semantic core review."]
    elif values == {"RUNTIME"}:
        classification, action = "RUNTIME_ONLY", "RUNTIME_RECHECK"
        notes = ["Only runtime evidence changed; recheck runtime evidence without rewriting product facts."]
    elif values <= {"EVIDENCE", "RUNTIME"}:
        classification, action = "EVIDENCE_ONLY", "DETERMINISTIC_EVIDENCE_RECHECK"
        notes = ["Only evidence/runtime artifacts changed; do not restart Producer/Reviewer chain."]
    else:
        classification, action = "UNKNOWN", "MANUAL_TRIAGE"
        notes = ["A changed file could not be safely classified; default to manual triage."]
    return {
        "schemaVersion": 1,
        "previousRevision": previous_revision,
        "currentRevision": current_revision,
        "classification": classification,
        "changedFiles": changed,
        "coreChanged": core_changed,
        "recommendedAction": action,
        "fileClasses": classes,
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--previous-revision", required=True)
    parser.add_argument("--current-revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = classify(args.previous, args.current, args.previous_revision, args.current_revision)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
