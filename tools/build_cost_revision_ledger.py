#!/usr/bin/env python3
"""Build a revision-bound ledger of observed time, transcript volume and repair activity.

The ledger deliberately separates observed values from estimated values. Estimated
tokens are derived from transcript bytes; they are not provider-reported token
counts. Human touch time is marked UNAVAILABLE unless an explicit source exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash
from trust_kernel import validate_schema_value


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_size(path: Path | None) -> int | None:
    if path is None or not path.is_file():
        return None
    return path.stat().st_size


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def elapsed_ms(start: Any, end: Any) -> float | None:
    first = parse_time(start)
    last = parse_time(end)
    if first is None or last is None:
        return None
    return round(max(0.0, (last - first).total_seconds() * 1000), 2)


def revision_number(revision: str) -> int:
    match = re.fullmatch(r"r(\d+)", revision)
    if not match:
        raise ValueError(f"revision must match r<number>, got {revision!r}")
    return int(match.group(1))


def next_revision(revision: str) -> str:
    return f"r{revision_number(revision) + 1}"


class LedgerBuilder:
    def __init__(self, run_root: Path, bundle: Path, workflow_id: str, final_revision: str) -> None:
        self.run_root = run_root
        self.bundle = bundle
        self.workflow_id = workflow_id
        self.final_revision = final_revision
        self.sources: dict[tuple[str, str], dict[str, Any]] = {}
        self.stages: list[dict[str, Any]] = []
        self.revisions: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "auditStatuses": [], "changedArtifacts": [], "sourceRefs": [],
            "artifactSnapshotSha256": None, "candidateSealPath": None, "candidateSealSha256": None,
        })
        self.warnings: list[str] = []
        self.evidence_gaps: list[str] = []
        self.budget: dict[str, Any] = {}
        self.repair_round_count = 0
        self.external_finding_count = 0
        self.consumer_report_count = 0
        self.consumer_reports: list[Path] = []

    def add_source(self, kind: str, path: Path | None, revision: str | None = None) -> str | None:
        if path is None:
            return None
        resolved = path.resolve()
        key = (kind, str(resolved))
        if key not in self.sources:
            available = resolved.is_file()
            self.sources[key] = {
                "kind": kind,
                "path": str(resolved),
                "sha256": sha256(resolved) if available else None,
                "availability": "AVAILABLE" if available else "MISSING",
                "revision": revision,
            }
            if not available:
                self.evidence_gaps.append(f"{kind}:MISSING:{resolved}")
        return str(resolved)

    def add_revision(self, revision: str | None, status: str | None, source: str | None) -> None:
        if not revision:
            return
        record = self.revisions[revision]
        if status and status not in record["auditStatuses"]:
            record["auditStatuses"].append(status)
        if source and source not in record["sourceRefs"]:
            record["sourceRefs"].append(source)

    def observe_candidate_seals(self) -> None:
        candidates = [self.bundle / ".delivery" / "candidate-seal.json"]
        revisions_dir = self.bundle / ".delivery" / "candidate-revisions"
        if revisions_dir.is_dir():
            candidates.extend(sorted(revisions_dir.glob("r*/.delivery/candidate-seal.json")))
        seen: set[str] = set()
        for path in candidates:
            if not path.is_file():
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            seal = load(path, {})
            revision = str(seal.get("revision") or "")
            if not revision:
                continue
            source = self.add_source("CANDIDATE_SEAL", path, revision)
            artifact_hashes = seal.get("artifactHashes") or {}
            record = self.revisions[revision]
            record["candidateSealPath"] = str(path.resolve())
            record["candidateSealSha256"] = sha256(path)
            record["artifactSnapshotSha256"] = canonical_hash(artifact_hashes) if artifact_hashes else None
            self.add_revision(revision, "CANDIDATE_SEALED", source)

    def observe_audit_stage(self, stage: dict[str, Any], source_path: Path | None, repair_round: int | None = None) -> None:
        if not isinstance(stage, dict) or not stage:
            return
        revision = str(stage.get("revision") or self.final_revision)
        source = self.add_source("AUDIT_STAGE", source_path, revision)
        self.add_revision(revision, str(stage.get("status") or "UNKNOWN"), source)
        telemetry = stage.get("telemetry") if isinstance(stage.get("telemetry"), dict) else {}
        metrics = telemetry.get("metrics") if isinstance(telemetry.get("metrics"), dict) else {}
        stage_elapsed = metrics.get("elapsedMs")
        availability = "AVAILABLE" if isinstance(stage_elapsed, (int, float)) else "PARTIAL"
        if not isinstance(stage_elapsed, (int, float)):
            stage_elapsed = elapsed_ms(stage.get("startedAt"), stage.get("finishedAt"))
            availability = "PARTIAL" if stage_elapsed is not None else "UNAVAILABLE"
        if telemetry.get("budget") and not self.budget:
            self.budget = dict(telemetry["budget"])
        stage_id = f"AUDIT-{revision}" + (f"-R{repair_round}" if repair_round is not None else "")
        self.stages.append({
            "stageId": stage_id,
            "stageType": "AUDIT",
            "revision": revision,
            "nextRevision": None,
            "status": str(stage.get("status") or "UNKNOWN"),
            "metricsAvailability": availability,
            "elapsedMs": stage_elapsed,
            "transcriptBytes": metrics.get("transcriptBytes") if isinstance(metrics.get("transcriptBytes"), int) else None,
            "estimatedTokens": metrics.get("estimatedTokens") if isinstance(metrics.get("estimatedTokens"), int) else None,
            "inputFiles": metrics.get("inputFiles") if isinstance(metrics.get("inputFiles"), int) else None,
            "contextPatterns": None,
            "jobs": metrics.get("jobs") if isinstance(metrics.get("jobs"), int) else None,
            "changedArtifacts": [],
            "sourceRefs": [value for value in [source, str(stage.get("telemetryPath") or "")] if value],
        })

    def observe_repair_cycle(self, path: Path) -> dict[str, Any]:
        report = load(path, {}) or {}
        if not report:
            return {}
        self.add_source("REPAIR_CYCLE", path, str(report.get("finalRevision") or self.final_revision))
        external_batch = report.get("externalFindingBatch")
        if external_batch:
            batch_path = Path(str(external_batch))
            batch = load(batch_path, {}) or {}
            self.external_finding_count = len(batch.get("findings") or [])
            import_run = report.get("externalImportRun") or {}
            status = "PASS" if import_run.get("returnCode") == 0 and self.external_finding_count else "SKIPPED"
            source = self.add_source("EXTERNAL_FINDING_BATCH", batch_path, str(report.get("finalRevision") or self.final_revision))
            self.stages.append({
                "stageId": "EXTERNAL-FINDING-INGEST",
                "stageType": "EXTERNAL_FINDING_INGEST",
                "revision": str(report.get("finalRevision") or self.final_revision),
                "nextRevision": None,
                "status": status,
                "metricsAvailability": "UNAVAILABLE",
                "elapsedMs": None,
                "transcriptBytes": None,
                "estimatedTokens": None,
                "inputFiles": None,
                "contextPatterns": None,
                "jobs": None,
                "changedArtifacts": [],
                "sourceRefs": [value for value in [source, str(path.resolve())] if value],
            })
            self.evidence_gaps.append("external-finding-ingest-duration:UNAVAILABLE")
        for index, round_record in enumerate(report.get("rounds") or []):
            revision = str(round_record.get("revision") or self.final_revision)
            stage = round_record.get("stage") if isinstance(round_record.get("stage"), dict) else {}
            stage_path = self.run_root / ".agents" / "audit" / f"stage-{revision}.json"
            self.observe_audit_stage(stage, stage_path, repair_round=index)
            repair_path_value = round_record.get("repairReport")
            if not repair_path_value:
                continue
            repair_path = Path(str(repair_path_value))
            repair = load(repair_path, {}) or {}
            if not repair:
                continue
            target_revision = next_revision(revision)
            changed = [str(item) for item in repair.get("changedArtifacts") or []]
            source = self.add_source("REPAIR_REPORT", repair_path, revision)
            self.revisions[revision]["changedArtifacts"].extend(item for item in changed if item not in self.revisions[revision]["changedArtifacts"])
            self.revisions[revision]["changedArtifacts"] = sorted(set(self.revisions[revision]["changedArtifacts"]))
            self.add_revision(target_revision, "REPAIR_TARGET", source)
            self.repair_round_count += 1
            self.stages.append({
                "stageId": f"REPAIR-{revision}-TO-{target_revision}",
                "stageType": "REPAIR",
                "revision": revision,
                "nextRevision": target_revision,
                "status": str(repair.get("status") or "UNKNOWN"),
                "metricsAvailability": "UNAVAILABLE",
                "elapsedMs": elapsed_ms(repair.get("startedAt"), repair.get("finishedAt")),
                "transcriptBytes": None,
                "estimatedTokens": None,
                "inputFiles": None,
                "contextPatterns": None,
                "jobs": None,
                "changedArtifacts": changed,
                "sourceRefs": [source] if source else [],
            })
            if self.stages[-1]["elapsedMs"] is None:
                self.evidence_gaps.append(f"repair-duration:{revision}->{target_revision}:UNAVAILABLE")
        return report

    def observe_runtime(self) -> None:
        runtime_dir = self.run_root / ".agents" / "runtime"
        if not runtime_dir.is_dir():
            return
        for record_path in sorted(runtime_dir.glob("*.json")):
            record = load(record_path, {}) or {}
            if not isinstance(record, dict) or not record.get("taskId"):
                continue
            source = self.add_source("AGENT_RUNTIME_RECORD", record_path)
            transcript_path = Path(str(record.get("transcriptPath") or "")) if record.get("transcriptPath") else None
            transcript = self.add_source("AGENT_TRANSCRIPT", transcript_path) if transcript_path else None
            transcript_bytes = file_size(transcript_path)
            observed_elapsed = elapsed_ms(record.get("startedAt"), record.get("finishedAt"))
            context_patterns = None
            task_manifest_value = record.get("taskManifest")
            if task_manifest_value:
                task_manifest = Path(str(task_manifest_value))
                self.add_source("TASK_MANIFEST", task_manifest)
                task = load(task_manifest, {}) or {}
                read_scope = task.get("readScope")
                if isinstance(read_scope, list):
                    context_patterns = len(read_scope)
            availability = "AVAILABLE" if observed_elapsed is not None and transcript_bytes is not None else "PARTIAL"
            if observed_elapsed is None:
                self.evidence_gaps.append(f"runtime-duration:{record.get('taskId')}:UNAVAILABLE")
            self.stages.append({
                "stageId": f"RUNTIME-{record.get('taskId')}",
                "stageType": "AGENT_RUNTIME",
                "revision": None,
                "nextRevision": None,
                "status": str(record.get("status") or "UNKNOWN"),
                "metricsAvailability": availability,
                "elapsedMs": observed_elapsed,
                "transcriptBytes": transcript_bytes,
                "estimatedTokens": (transcript_bytes + 3) // 4 if transcript_bytes is not None else None,
                "inputFiles": None,
                "contextPatterns": context_patterns,
                "jobs": 1,
                "changedArtifacts": [],
                "sourceRefs": [value for value in [source, transcript] if value],
            })

    def observe_consumer_reports(self, paths: list[Path]) -> None:
        seen: set[Path] = set()
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            report = load(resolved, {}) or {}
            if not report:
                self.warnings.append(f"consumer report unavailable: {resolved}")
                self.evidence_gaps.append(f"consumer-report:MISSING:{resolved}")
                continue
            self.consumer_report_count += 1
            self.consumer_reports.append(resolved)
            revision = str(report.get("targetRevision") or self.final_revision)
            source = self.add_source("CONSUMER_ACCEPTANCE_REPORT", resolved, revision)
            self.add_revision(revision, str(report.get("status") or "UNKNOWN"), source)
            self.stages.append({
                "stageId": f"CONSUMER-{report.get('reportId') or resolved.stem}",
                "stageType": "CONSUMER_ACCEPTANCE",
                "revision": revision,
                "nextRevision": None,
                "status": str(report.get("status") or "UNKNOWN"),
                "metricsAvailability": "UNAVAILABLE",
                "elapsedMs": None,
                "transcriptBytes": None,
                "estimatedTokens": None,
                "inputFiles": None,
                "contextPatterns": None,
                "jobs": None,
                "changedArtifacts": [],
                "sourceRefs": [source] if source else [],
            })
            self.evidence_gaps.append(f"consumer-review-duration:{report.get('reportId') or resolved.stem}:UNAVAILABLE")

    def observe_supporting_sources(self) -> None:
        package_path = self.run_root / ".agents" / "quality" / "package-evidence.json"
        package = load(package_path, {}) or {}
        self.add_source("PACKAGE_EVIDENCE", package_path, self.final_revision)
        runtime = package.get("runtimeEvidencePath")
        if runtime:
            self.add_source("RUNTIME_EVIDENCE", Path(str(runtime)))
        telemetry_path = self.run_root / ".agents" / "audit" / "run-cost-telemetry.json"
        telemetry = load(telemetry_path, {}) or {}
        if telemetry:
            self.add_source("RUN_COST_TELEMETRY", telemetry_path, str(telemetry.get("revision") or self.final_revision))
            if telemetry.get("budget") and not self.budget:
                self.budget = dict(telemetry["budget"])
        repair_path = self.run_root / ".agents" / "audit" / "repair-cycle-report.json"
        self.observe_repair_cycle(repair_path)
        standalone_stage = self.run_root / ".agents" / "audit" / "delivery-audit-stage.json"
        if not self.repair_round_count and standalone_stage.is_file():
            self.observe_audit_stage(load(standalone_stage, {}) or {}, standalone_stage)
        seen_audits = {(item.get("revision"), item.get("stageId")) for item in self.stages if item.get("stageType") == "AUDIT"}
        for stage_path in sorted((self.run_root / ".agents" / "audit").glob("stage-r*.json")):
            stage = load(stage_path, {}) or {}
            key = (stage.get("revision"), f"AUDIT-{stage.get('revision')}")
            if key not in seen_audits:
                self.observe_audit_stage(stage, stage_path)
                seen_audits.add(key)

    def finish(self) -> dict[str, Any]:
        final = self.revisions.setdefault(self.final_revision, {
            "auditStatuses": [], "changedArtifacts": [], "sourceRefs": [],
            "artifactSnapshotSha256": None, "candidateSealPath": None, "candidateSealSha256": None,
        })
        if not final["auditStatuses"]:
            final["auditStatuses"].append("NOT_OBSERVED")
        revisions = [
            {"revision": revision, **record}
            for revision, record in sorted(self.revisions.items(), key=lambda item: revision_number(item[0]))
        ]
        audit_stages = [item for item in self.stages if item["stageType"] == "AUDIT"]
        audit_complete = bool(audit_stages) and all(item["metricsAvailability"] == "AVAILABLE" for item in audit_stages)
        runtime_stages = [item for item in self.stages if item["stageType"] == "AGENT_RUNTIME"]
        runtime_complete = all(item["metricsAvailability"] == "AVAILABLE" for item in runtime_stages) if runtime_stages else True
        all_stage_metrics_complete = all(item["metricsAvailability"] == "AVAILABLE" for item in self.stages)
        if not audit_stages and not runtime_stages:
            availability = "UNAVAILABLE"
            status = "INSUFFICIENT"
            self.evidence_gaps.append("machine-telemetry:UNAVAILABLE")
        elif audit_complete and runtime_complete and all_stage_metrics_complete:
            availability = "COMPLETE"
            status = "COMPLETE"
        else:
            availability = "PARTIAL"
            status = "PARTIAL"
        if not audit_stages:
            self.evidence_gaps.append("audit-telemetry:UNAVAILABLE")
        if any(item["metricsAvailability"] == "UNAVAILABLE" for item in self.stages):
            self.warnings.append("One or more stages expose no timing telemetry; elapsed/token totals are lower bounds, not end-to-end cost.")
        self.evidence_gaps.append("human-touch-time:UNAVAILABLE")
        self.warnings.append("estimatedTranscriptTokens is ceil(transcriptBytes / 4), not provider-reported input/output token usage.")
        sources = sorted(self.sources.values(), key=lambda item: (item["kind"], item["path"]))
        metrics = {
            "observedElapsedMs": round(sum(float(item["elapsedMs"] or 0) for item in self.stages), 2),
            "observedTranscriptBytes": sum(int(item["transcriptBytes"] or 0) for item in self.stages),
            "estimatedTranscriptTokens": sum(int(item["estimatedTokens"] or 0) for item in self.stages),
            "auditJobs": sum(int(item["jobs"] or 0) for item in audit_stages),
            "auditInputFiles": sum(int(item["inputFiles"] or 0) for item in audit_stages),
            "contextPatterns": sum(int(item["contextPatterns"] or 0) for item in self.stages),
            "runtimeRecords": len(runtime_stages),
            "repairRounds": self.repair_round_count,
            "revisionCount": len(revisions),
            "externalFindings": self.external_finding_count,
            "consumerReports": self.consumer_report_count,
        }
        source_identity = [{"kind": item["kind"], "path": item["path"], "sha256": item["sha256"]} for item in sources]
        ledger = {
            "schemaVersion": 1,
            "ledgerId": "CRL-" + canonical_hash({"workflowId": self.workflow_id, "finalRevision": self.final_revision, "sources": source_identity})[:16],
            "workflowId": self.workflow_id,
            "finalRevision": self.final_revision,
            "status": status,
            "metricsAvailability": availability,
            "sources": sources,
            "revisions": revisions,
            "stages": self.stages,
            "metrics": metrics,
            "humanTouch": {
                "status": "UNAVAILABLE",
                "elapsedMs": None,
                "reason": "No human timer, review duration or calibrated human-touch source is attached to this run.",
            },
            "warnings": sorted(set(self.warnings)),
            "evidenceGaps": sorted(set(self.evidence_gaps)),
            "createdAt": now(),
        }
        if self.budget:
            ledger["budget"] = self.budget
        return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--workflow-id")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--consumer-report", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--strict", action="store_true", help="Fail when the ledger is not COMPLETE.")
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    bundle = (args.bundle or (run_root / "01-delivery")).resolve()
    package = load(run_root / ".agents" / "quality" / "package-evidence.json", {}) or {}
    seal = load(bundle / ".delivery" / "candidate-seal.json", {}) or {}
    workflow_id = args.workflow_id or package.get("workflowId") or seal.get("workflowId")
    final_revision = args.revision or seal.get("revision") or package.get("revision")
    if not workflow_id or not final_revision:
        print(json.dumps({"status": "BLOCKED", "error": "workflow id and final revision are required when inference fails"}, ensure_ascii=False))
        return 1
    builder = LedgerBuilder(run_root, bundle, str(workflow_id), str(final_revision))
    builder.observe_supporting_sources()
    builder.observe_candidate_seals()
    builder.observe_runtime()
    builder.observe_consumer_reports(args.consumer_report)
    ledger = builder.finish()
    issues = validate_schema_value(ledger, "cost-revision-ledger.schema.json")
    if issues:
        print(json.dumps({"status": "BLOCKED", "errors": issues}, ensure_ascii=False))
        return 1
    out = (args.out or (run_root / ".agents" / "quality" / "cost-revision-ledger.json")).resolve()
    save(out, ledger)
    print(json.dumps({
        "status": ledger["status"],
        "metricsAvailability": ledger["metricsAvailability"],
        "ledgerId": ledger["ledgerId"],
        "finalRevision": ledger["finalRevision"],
        "revisions": ledger["metrics"]["revisionCount"],
        "repairRounds": ledger["metrics"]["repairRounds"],
        "estimatedTranscriptTokens": ledger["metrics"]["estimatedTranscriptTokens"],
        "out": str(out),
    }, ensure_ascii=False))
    return 0 if ledger["status"] == "COMPLETE" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
