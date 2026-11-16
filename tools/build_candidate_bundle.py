#!/usr/bin/env python3
"""Build and seal the immutable candidate bundle used by pre-finalization audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FR_RE = re.compile(r"\bFR-\d{3}\b")
AC_RE = re.compile(r"\bAC-\d{3}\b")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_requirements(prd: str) -> list[dict[str, Any]]:
    lines = prd.splitlines()
    found: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line_number, line in enumerate(lines, start=1):
        match = FR_RE.search(line)
        if match:
            if current:
                found.append(current)
            current = {
                "id": match.group(0),
                "title": line[match.end():].lstrip(" :-：").strip() or line.strip(),
                "normative": line.strip(),
                "acceptanceCriteria": [],
                "sourceRef": f"PRD_DELIVERY.md:{line_number}",
            }
            priority = re.search(r"\bP[012]\b", line)
            if priority:
                current["priority"] = priority.group(0)
        elif current:
            current["acceptanceCriteria"] = sorted(set(current["acceptanceCriteria"] + AC_RE.findall(line)))
    if current:
        found.append(current)
    return found


def write_requirements(path: Path, prd_path: Path, workflow_id: str, requirement_id: str, revision: str) -> None:
    save(path, {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "requirementId": requirement_id or workflow_id,
        "revision": revision,
        "sourcePrd": prd_path.name,
        "sourcePrdSha256": sha256(prd_path),
        "requirements": extract_requirements(prd_path.read_text(encoding="utf-8")),
        "generatedAt": now(),
    })


def write_issue_description(path: Path, prd_path: Path, requirement_name: str, requirement_id: str) -> None:
    lines = [line.strip() for line in prd_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = next((line for line in lines if not line.startswith("#") and not FR_RE.search(line)), requirement_name)
    functional = [line for line in lines if FR_RE.search(line)]
    body = [
        f"# {requirement_name}", "", "## 1. 需求背景", summary, "",
        "## 2. 需求目标",
        f"按当前 PRD 完成需求 {requirement_id or requirement_name} 的定义、评审和交付准备。",
        "", "## 3. 涉及功能",
    ]
    body.extend(f"- {line}" for line in functional[:8] or ["见 PRD_DELIVERY.md。"])
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def write_candidate_reports(gates_path: Path, workflow_path: Path, revision: str, workflow_id: str) -> None:
    gates = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
    rows = "\n".join(f"| {gate} | NOT_EXECUTED | Candidate audit pending |" for gate in gates)
    gates_path.write_text(
        f"# Candidate Gates\n\nWorkflow: `{workflow_id}`  \nRevision: `{revision}`\n\n| Gate | Result | Note |\n|---|---|---|\n{rows}\n",
        encoding="utf-8",
    )
    workflow_path.write_text(
        f"# Candidate Workflow\n\n- Workflow: `{workflow_id}`\n- Candidate revision: `{revision}`\n- Status: `CANDIDATE_SEALED`\n- Finalization: pending independent gates and Audit Track\n\n| Gate | Result |\n|---|---|\n" +
        "\n".join(f"| {gate} | NOT_EXECUTED |" for gate in gates) + "\n",
        encoding="utf-8",
    )


def collect_artifacts(bundle: Path, prd: Path, overview: Path, jira: Path, prototype: Path | None, manifest: Path | None, workflow_id: str, requirement_id: str, requirement_name: str, revision: str, refresh_projections: bool = False) -> dict[str, Path]:
    for path in (prd, overview, jira):
        if not path.is_file():
            raise FileNotFoundError(f"required candidate artifact missing: {path}")
    if prototype and not manifest:
        raise ValueError("Prototype candidate requires prototype-manifest.json")
    if manifest and not prototype:
        raise ValueError("prototype-manifest.json requires Prototype.html")
    requirements = bundle / "requirements.json"
    if refresh_projections or not requirements.is_file():
        write_requirements(requirements, prd, workflow_id, requirement_id, revision)
    issue = bundle / "Issue_Description.md"
    if refresh_projections or not issue.is_file():
        write_issue_description(issue, prd, requirement_name, requirement_id)
    gates = bundle / "Gates.md"
    workflow = bundle / "Workflow.md"
    if refresh_projections or not gates.is_file() or not workflow.is_file():
        write_candidate_reports(gates, workflow, revision, workflow_id)
    artifacts = {
        "Issue_Description.md": issue,
        "Overview.html": overview,
        "PRD_DELIVERY.md": prd,
        "Jira_Description.md": jira,
        "Gates.md": gates,
        "Workflow.md": workflow,
        "requirements.json": requirements,
    }
    if prototype:
        artifacts["Prototype.html"] = prototype
        artifacts["prototype-manifest.json"] = manifest  # type: ignore[assignment]
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--requirement-id", default="")
    parser.add_argument("--requirement-name", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--overview", type=Path, required=True)
    parser.add_argument("--jira", type=Path, required=True)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--refresh-projections", action="store_true", help="Regenerate deterministic candidate projections for a new revision.")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    dd = bundle / ".delivery"
    seal_path = dd / "candidate-seal.json"
    final_path = dd / "final-seal.json"
    report_path = args.out.resolve() if args.out else dd / "candidate-build-report.json"
    errors: list[str] = []
    if final_path.exists():
        errors.append("final-seal.json already exists; cannot rebuild candidate seal")
    try:
        artifacts = collect_artifacts(bundle, args.prd.resolve(), args.overview.resolve(), args.jira.resolve(), args.prototype.resolve() if args.prototype else None, args.manifest.resolve() if args.manifest else None, args.workflow_id, args.requirement_id, args.requirement_name, args.revision)
    except (OSError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        save(report_path, {"schemaVersion": 1, "status": "BLOCKED", "workflowId": args.workflow_id, "revision": args.revision, "frozenCopy": None, "artifactHashes": {}, "errors": errors, "createdAt": now()})
        print(json.dumps({"status": "BLOCKED", "errors": errors, "report": str(report_path)}, ensure_ascii=False))
        return 1
    frozen = dd / "candidate-revisions" / args.revision
    computed: dict[str, str] = {}
    if not errors:
        dd.joinpath("candidate-revisions").mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{args.revision}-candidate-", dir=str(dd / "candidate-revisions")))
        try:
            for name, source in sorted(artifacts.items()):
                if not source.is_file():
                    errors.append(f"candidate source is not a file: {source}")
                    continue
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                computed[name] = sha256(destination)
            if not errors:
                if frozen.exists():
                    existing = {path.relative_to(frozen).as_posix(): sha256(path) for path in frozen.rglob("*") if path.is_file()}
                    if existing != computed:
                        errors.append("candidate frozen copy already exists with different artifact hashes")
                else:
                    staging.rename(frozen)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    existing_seal: dict[str, Any] | None = None
    if seal_path.exists():
        try:
            existing_seal = load(seal_path)
        except Exception as exc:
            errors.append(f"existing candidate-seal.json is invalid: {exc}")
    expected_seal = {"bundleId": f"{args.workflow_id}-{args.revision}", "workflowId": args.workflow_id, "revision": args.revision, "status": "CANDIDATE_SEALED", "frozenCopy": f".delivery/candidate-revisions/{args.revision}", "artifactHashes": computed, "createdAt": now()}
    if existing_seal and existing_seal.get("revision") == args.revision:
        if existing_seal.get("frozenCopy") != expected_seal["frozenCopy"] or existing_seal.get("artifactHashes") != computed:
            errors.append("existing candidate seal does not match current candidate artifacts")
        else:
            expected_seal = existing_seal
    if not errors:
        save(seal_path, expected_seal)
    report = {"schemaVersion": 1, "status": "PASS" if not errors else "BLOCKED", "workflowId": args.workflow_id, "revision": args.revision, "frozenCopy": str(frozen), "candidateSeal": str(seal_path), "artifactHashes": computed, "reused": existing_seal is not None and not errors, "errors": errors, "createdAt": now()}
    save(report_path, report)
    print(json.dumps({"status": report["status"], "frozenCopy": str(frozen), "candidateSeal": str(seal_path), "artifacts": len(computed), "errors": errors, "report": str(report_path)}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
