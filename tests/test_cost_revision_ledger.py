import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILDER = TOOLS / "build_cost_revision_ledger.py"


class CostRevisionLedgerTests(unittest.TestCase):
    def fixture(self, root: Path):
        run = root / "run"
        bundle = run / "01-delivery"
        dd = bundle / ".delivery"
        audit = run / ".agents" / "audit"
        runtime = run / ".agents" / "runtime"
        quality = run / ".agents" / "quality"
        tasks = run / ".agents" / "tasks"
        transcripts = runtime / "transcripts"
        for path in (dd, audit, runtime, quality, tasks, transcripts):
            path.mkdir(parents=True, exist_ok=True)

        seal_r1 = {
            "schemaVersion": 1,
            "bundleId": "WF-COST-r1",
            "workflowId": "WF-COST",
            "revision": "r1",
            "status": "CANDIDATE_SEALED",
            "artifactHashes": {"PRD_DELIVERY.md": "a" * 64},
        }
        seal_r2 = {
            "schemaVersion": 1,
            "bundleId": "WF-COST-r2",
            "workflowId": "WF-COST",
            "revision": "r2",
            "status": "CANDIDATE_SEALED",
            "artifactHashes": {"PRD_DELIVERY.md": "b" * 64},
        }
        for revision, payload in (("r1", seal_r1), ("r2", seal_r2)):
            directory = dd / "candidate-revisions" / revision / ".delivery"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "candidate-seal.json").write_text(json.dumps(payload), encoding="utf-8")
        (dd / "candidate-seal.json").write_text(json.dumps(seal_r2), encoding="utf-8")

        stage_r1 = {
            "schemaVersion": 1,
            "workflowId": "WF-COST",
            "revision": "r1",
            "status": "AUDIT_BLOCKED",
            "startedAt": "2026-11-23T01:00:00+00:00",
            "finishedAt": "2026-11-23T01:00:10+00:00",
            "telemetry": {
                "budget": {"maxTotalSeconds": 3600, "maxJobSeconds": 300, "maxContextFiles": 200, "maxTranscriptBytes": 10000000, "maxRepairRounds": 2},
                "metrics": {"elapsedMs": 10000, "jobs": 2, "inputFiles": 7, "transcriptBytes": 400, "estimatedTokens": 100},
            },
        }
        stage_r2 = {
            "schemaVersion": 1,
            "workflowId": "WF-COST",
            "revision": "r2",
            "status": "AUDIT_PASS",
            "startedAt": "2026-11-23T01:01:00+00:00",
            "finishedAt": "2026-11-23T01:01:20+00:00",
            "telemetry": {
                "budget": {"maxTotalSeconds": 3600, "maxJobSeconds": 300, "maxContextFiles": 200, "maxTranscriptBytes": 10000000, "maxRepairRounds": 2},
                "metrics": {"elapsedMs": 20000, "jobs": 1, "inputFiles": 5, "transcriptBytes": 200, "estimatedTokens": 50},
            },
        }
        repair_report = {
            "schemaVersion": 1,
            "status": "PASS",
            "changedArtifacts": ["PRD_DELIVERY.md", "Overview.html"],
            "startedAt": "2026-11-23T01:00:30+00:00",
            "finishedAt": "2026-11-23T01:00:40+00:00",
        }
        (audit / "repair-report-r1-to-r2.json").write_text(json.dumps(repair_report), encoding="utf-8")
        external_batch = {
            "schemaVersion": 1,
            "workflowId": "WF-COST",
            "revision": "r1",
            "findings": [{"findingId": "EXT-1"}],
        }
        (audit / "external-findings-r1.json").write_text(json.dumps(external_batch), encoding="utf-8")
        cycle = {
            "schemaVersion": 1,
            "status": "AUDIT_PASS",
            "workflowId": "WF-COST",
            "finalRevision": "r2",
            "rounds": [
                {"round": 0, "revision": "r1", "stage": stage_r1, "repairReport": str(audit / "repair-report-r1-to-r2.json")},
                {"round": 1, "revision": "r2", "stage": stage_r2},
            ],
            "externalFindingBatch": str(audit / "external-findings-r1.json"),
            "externalImportRun": {"returnCode": 0},
        }
        (audit / "repair-cycle-report.json").write_text(json.dumps(cycle), encoding="utf-8")

        task_manifest = tasks / "PRD-PRODUCE.task.json"
        task_manifest.write_text(json.dumps({"taskId": "PRD-PRODUCE", "readScope": ["01-delivery/**", "requirements/**"]}), encoding="utf-8")
        transcript = transcripts / "PRD-PRODUCE.log"
        transcript.write_text("x" * 120, encoding="utf-8")
        runtime_record = {
            "schemaVersion": 1,
            "taskId": "PRD-PRODUCE",
            "status": "SUCCEEDED",
            "startedAt": "2026-11-23T00:59:00+00:00",
            "finishedAt": "2026-11-23T00:59:03+00:00",
            "taskManifest": str(task_manifest),
            "transcriptPath": str(transcript),
        }
        (runtime / "PRD-PRODUCE.json").write_text(json.dumps(runtime_record), encoding="utf-8")

        package = {
            "schemaVersion": 1,
            "workflowId": "WF-COST",
            "artifactProfile": "PRD_ONLY",
            "revision": "r2",
            "artifacts": [{"kind": "PRD", "path": "PRD_DELIVERY.md", "sha256": "b" * 64}],
            "gates": {},
            "technicalGapsPath": "technical-gaps.json",
            "artifactQualityPath": "artifact-quality.json",
            "createdAt": "2026-11-23T01:02:00+00:00",
        }
        (quality / "package-evidence.json").write_text(json.dumps(package), encoding="utf-8")

        consumer_report = {
            "schemaVersion": 1,
            "reportId": "CAR-1",
            "workflowId": "WF-COST",
            "caseId": "CASE-1",
            "targetRevision": "r2",
            "caseClassification": "REAL",
            "evaluationMode": "AGENT_CONSUMER_PROXY",
            "status": "PASS",
            "m7ExitEvidenceEligible": True,
            "humanConsumerReviewRequired": True,
            "productManager": {},
            "architect": {},
            "checks": [],
            "findings": [],
            "metrics": {},
            "artifactHashes": {},
            "contentSha256": "c" * 64,
            "createdAt": "2026-11-23T01:03:00+00:00",
        }
        consumer_path = root / "consumer-report.json"
        consumer_path.write_text(json.dumps(consumer_report), encoding="utf-8")
        return run, consumer_path

    def test_builds_revision_cost_ledger_and_preserves_metric_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            run, consumer = self.fixture(Path(td))
            out = run / ".agents" / "quality" / "cost-revision-ledger.json"
            process = subprocess.run([
                sys.executable, str(BUILDER), "--run-root", str(run),
                "--workflow-id", "WF-COST", "--bundle", str(run / "01-delivery"),
                "--revision", "r2", "--consumer-report", str(consumer), "--out", str(out),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            ledger = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(ledger["status"], "PARTIAL")
            self.assertEqual(ledger["finalRevision"], "r2")
            self.assertEqual(ledger["metrics"]["revisionCount"], 2)
            self.assertEqual(ledger["metrics"]["repairRounds"], 1)
            self.assertEqual(ledger["metrics"]["externalFindings"], 1)
            self.assertEqual(ledger["metrics"]["consumerReports"], 1)
            self.assertEqual(ledger["metrics"]["auditJobs"], 3)
            self.assertEqual(ledger["metrics"]["auditInputFiles"], 12)
            self.assertEqual(ledger["metrics"]["estimatedTranscriptTokens"], 180)
            self.assertEqual(ledger["humanTouch"]["status"], "UNAVAILABLE")
            self.assertIn("REPAIR_TARGET", ledger["revisions"][1]["auditStatuses"])
            self.assertTrue(all(item["sha256"] for item in ledger["sources"] if item["availability"] == "AVAILABLE"))

    def test_missing_machine_telemetry_is_insufficient_not_zero_cost(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = root / "run"
            (run / ".agents" / "quality").mkdir(parents=True)
            out = run / ".agents" / "quality" / "cost-revision-ledger.json"
            process = subprocess.run([
                sys.executable, str(BUILDER), "--run-root", str(run),
                "--workflow-id", "WF-EMPTY", "--revision", "r1", "--out", str(out),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            ledger = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(ledger["status"], "INSUFFICIENT")
            self.assertEqual(ledger["metricsAvailability"], "UNAVAILABLE")
            self.assertIn("machine-telemetry:UNAVAILABLE", ledger["evidenceGaps"])


if __name__ == "__main__":
    unittest.main()
