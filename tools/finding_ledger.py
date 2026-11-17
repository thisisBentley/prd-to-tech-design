#!/usr/bin/env python3
"""Persist audit findings with stable identity and bounded repair lifecycle."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL_STATUSES = {"resolved", "accepted_risk", "closed_by_decision"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_name(finding: dict[str, Any]) -> str:
    explicit = str(finding.get("artifact") or "").strip()
    if explicit:
        return explicit
    for ref in finding.get("evidenceRefs") or []:
        name = Path(str(ref).split("#", 1)[0]).name
        if name:
            return name
    return "UNKNOWN"


def ledger_metrics(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(entries),
        "openBlocking": sum(1 for item in entries if item["severity"] == "BLOCKING" and item["status"] not in TERMINAL_STATUSES),
        "unresolved": sum(1 for item in entries if item["status"] not in TERMINAL_STATUSES),
        "resolved": sum(1 for item in entries if item["status"] in TERMINAL_STATUSES),
        "repairAttempts": sum(int(item.get("repairAttempts", 0)) for item in entries),
    }


def empty_ledger(workflow_id: str, revision: str) -> dict[str, Any]:
    ledger_id = "finding-ledger-" + hashlib.sha256(f"{workflow_id}:{revision}".encode()).hexdigest()[:12]
    return {
        "schemaVersion": 1,
        "ledgerId": ledger_id,
        "workflowId": workflow_id,
        "currentRevision": revision,
        "entries": [],
        "metrics": ledger_metrics([]),
        "updatedAt": now(),
    }


def sync_ledger(ledger_path: Path, findings_path: Path, workflow_id: str, revision: str) -> dict[str, Any]:
    ledger = load(ledger_path) if ledger_path.is_file() else empty_ledger(workflow_id, revision)
    if ledger.get("workflowId") != workflow_id:
        raise ValueError(f"ledger workflowId {ledger.get('workflowId')!r} != {workflow_id!r}")
    payload = load(findings_path)
    seen: set[str] = set()
    by_id = {str(item["findingId"]): item for item in ledger.get("entries", [])}
    for finding in payload.get("findings") or []:
        finding_id = str(finding.get("findingId") or "").strip()
        if not finding_id:
            raise ValueError("audit finding is missing findingId")
        if finding_id in seen:
            continue
        seen.add(finding_id)
        timestamp = now()
        existing = by_id.get(finding_id)
        if existing is None:
            entry = {
                "findingId": finding_id,
                "title": str(finding.get("title") or finding_id),
                "severity": str(finding.get("severity") or "BLOCKING"),
                "status": "open",
                "rootCauseId": str(finding.get("rootCauseId") or finding_id),
                "repairClass": str(finding.get("repairClass") or "UNKNOWN"),
                "owners": [str(finding.get("owner") or "producer")],
                "ruleIds": [str(item) for item in (finding.get("ruleIds") or finding.get("policyRuleIds") or []) if item],
                "artifacts": [artifact_name(finding)],
                "evidenceRefs": [str(item) for item in finding.get("evidenceRefs") or []],
                "impact": str(finding.get("impact") or "Audit finding blocks delivery readiness."),
                "closeCondition": str(finding.get("closeCondition") or "Resolve the finding and pass a full re-audit."),
                "expectedInvariant": str(finding.get("expectedInvariant") or ""),
                "firstSeenRevision": revision,
                "lastSeenRevision": revision,
                "firstSeenAt": timestamp,
                "lastSeenAt": timestamp,
                "unresolvedRounds": 1,
                "occurrenceCount": 1,
                "repairAttempts": 0,
                "history": [{"event": "observed", "revision": revision, "at": timestamp, "evidenceRefs": [str(findings_path)]}],
            }
            ledger.setdefault("entries", []).append(entry)
            by_id[finding_id] = entry
            continue
        last_event = str((existing.get("history") or [{}])[-1].get("event", ""))
        resumed_after_absence = last_event == "not_observed_pending_full_pass"
        reopened = existing["status"] in TERMINAL_STATUSES or resumed_after_absence
        existing["status"] = "reopened" if reopened else "open"
        existing["title"] = str(finding.get("title") or existing["title"])
        existing["severity"] = str(finding.get("severity") or existing["severity"])
        existing["rootCauseId"] = str(finding.get("rootCauseId") or existing["rootCauseId"])
        existing["repairClass"] = str(finding.get("repairClass") or existing["repairClass"])
        owner = str(finding.get("owner") or "").strip()
        if owner and owner not in existing["owners"]:
            existing["owners"].append(owner)
        for rule in finding.get("ruleIds") or finding.get("policyRuleIds") or []:
            if rule and rule not in existing["ruleIds"]:
                existing["ruleIds"].append(rule)
        for ref in finding.get("evidenceRefs") or []:
            if ref and ref not in existing["evidenceRefs"]:
                existing["evidenceRefs"].append(ref)
        existing["lastSeenRevision"] = revision
        existing["lastSeenAt"] = timestamp
        existing["unresolvedRounds"] = 1 if reopened else int(existing.get("unresolvedRounds", 0)) + 1
        existing["occurrenceCount"] = int(existing.get("occurrenceCount", 0)) + 1
        existing["history"].append({"event": "reopened" if reopened else "observed_again", "revision": revision, "at": timestamp, "evidenceRefs": [str(findings_path)]})
    for entry in ledger.get("entries", []):
        if entry["findingId"] not in seen and entry["status"] not in TERMINAL_STATUSES:
            entry["history"].append({"event": "not_observed_pending_full_pass", "revision": revision, "at": now(), "evidenceRefs": [str(findings_path)]})
    ledger["currentRevision"] = revision
    ledger["metrics"] = ledger_metrics(ledger.get("entries", []))
    ledger["updatedAt"] = now()
    save(ledger_path, ledger)
    return ledger


def mark_repairing(ledger_path: Path, target_revision: str, finding_ids: set[str] | None = None) -> dict[str, Any]:
    ledger = load(ledger_path)
    for entry in ledger.get("entries", []):
        if entry["status"] in TERMINAL_STATUSES:
            continue
        if finding_ids is not None and entry["findingId"] not in finding_ids:
            continue
        entry["status"] = "in_progress"
        entry["repairRevision"] = target_revision
        entry["repairAttempts"] = int(entry.get("repairAttempts", 0)) + 1
        entry["history"].append({"event": "repair_started", "revision": target_revision, "at": now()})
    ledger["metrics"] = ledger_metrics(ledger.get("entries", []))
    ledger["updatedAt"] = now()
    save(ledger_path, ledger)
    return ledger


def close_ledger(ledger_path: Path, revision: str, evidence_refs: list[str]) -> dict[str, Any]:
    ledger = load(ledger_path)
    for entry in ledger.get("entries", []):
        if entry["status"] in TERMINAL_STATUSES:
            continue
        entry["status"] = "resolved"
        entry["resolutionRevision"] = revision
        entry["resolutionEvidence"] = list(dict.fromkeys([*(entry.get("resolutionEvidence") or []), *evidence_refs]))
        entry["history"].append({"event": "resolved_by_full_reaudit", "revision": revision, "at": now(), "evidenceRefs": evidence_refs})
    ledger["currentRevision"] = revision
    ledger["metrics"] = ledger_metrics(ledger.get("entries", []))
    ledger["updatedAt"] = now()
    save(ledger_path, ledger)
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--findings", type=Path, required=True)
    sync.add_argument("--workflow-id", required=True)
    sync.add_argument("--revision", required=True)
    repairing = sub.add_parser("repairing")
    repairing.add_argument("--target-revision", required=True)
    repairing.add_argument("--finding-id", action="append")
    close = sub.add_parser("close")
    close.add_argument("--revision", required=True)
    close.add_argument("--evidence", action="append", required=True)
    args = parser.parse_args()
    if args.command == "sync":
        ledger = sync_ledger(args.ledger.resolve(), args.findings.resolve(), args.workflow_id, args.revision)
        status = "SYNCED"
    elif args.command == "repairing":
        ledger = mark_repairing(args.ledger.resolve(), args.target_revision, set(args.finding_id) if args.finding_id else None)
        status = "REPAIRING"
    else:
        ledger = close_ledger(args.ledger.resolve(), args.revision, args.evidence)
        status = "CLOSED"
    if args.out:
        save(args.out.resolve(), ledger)
    print(json.dumps({"status": status, "ledger": str(args.ledger.resolve()), "metrics": ledger["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
