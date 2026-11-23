import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILD = TOOLS / "build_project_episode.py"
VALIDATE = TOOLS / "validate_project_episode.py"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class ProjectEpisodeTests(unittest.TestCase):
    def fixture(self, root):
        revision = "r2"
        def write(name, data):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        procedure = write("control/procedure.json", {
            "schemaVersion": 1, "workflowId": "WF-EP", "revision": "r1",
            "goalContract": {"objectiveText": "Deliver customer export"},
        })
        handoff = write("handoffs/final.json", {
            "schemaVersion": 1, "workflowId": "WF-EP", "revision": revision,
        })
        findings = write("delivery/findings.json", {
            "schemaVersion": 1, "workflowId": "WF-EP", "currentRevision": revision,
            "entries": [
                {"findingId": "F-1", "rootCauseId": "RC-1", "status": "resolved"},
                {"findingId": "F-2", "rootCauseId": "RC-2", "status": "open"},
            ],
            "metrics": {"total": 2, "openBlocking": 1, "unresolved": 1, "resolved": 1, "repairAttempts": 1},
        })
        repair_report = write("audit/repair-r1-r2.json", {
            "schemaVersion": 1, "status": "PASS", "changedArtifacts": ["PRD_DELIVERY.md", "Overview.html"],
        })
        repair_cycle = write("audit/repair-cycle.json", {
            "schemaVersion": 1, "workflowId": "WF-EP", "finalRevision": revision,
            "status": "AUDIT_PASS", "rounds": [{"round": 0, "revision": "r1", "repairReport": str(repair_report)}],
        })
        cost = write("quality/cost.json", {
            "schemaVersion": 1, "workflowId": "WF-EP", "finalRevision": revision,
            "status": "PARTIAL", "metricsAvailability": "PARTIAL",
            "revisions": [{"revision": "r1", "auditStatuses": ["AUDIT_BLOCKED"], "sourceRefs": []}, {"revision": "r2", "auditStatuses": ["AUDIT_PASS"], "sourceRefs": []}],
            "stages": [{"stageType": "REPAIR", "revision": "r1", "nextRevision": "r2", "status": "AUDIT_PASS", "sourceRefs": []}],
            "metrics": {"revisionCount": 2, "repairRounds": 1},
        })
        gate = write("quality/final-gate.json", {"schemaVersion": 2, "gate": "Q1", "result": "PASS", "blockingCount": 0, "findings": []})
        consumer = write("consumer/report.json", {
            "schemaVersion": 1, "reportId": "CAR-EP", "workflowId": "WF-EP", "caseId": "CASE-EP",
            "targetRevision": revision, "caseClassification": "REAL", "evaluationMode": "AGENT_CONSUMER_PROXY",
            "status": "PASS", "m7ExitEvidenceEligible": True, "humanConsumerReviewRequired": True,
            "productManager": {}, "architect": {}, "checks": [], "findings": [], "metrics": {},
            "artifactHashes": {}, "contentSha256": "a" * 64, "createdAt": "2026-11-23T00:00:00+00:00",
        })
        decision_dir = root / "decisions"
        write("decisions/D-1.json", {"status": "confirmed", "decisionId": "D-1"})
        return {
            "procedure": procedure, "handoff": handoff, "findings": findings,
            "repair": repair_cycle, "cost": cost, "gate": gate, "consumer": consumer,
            "decisions": decision_dir,
        }

    def args(self, paths, out):
        return [
            BUILD, "--run-root", out.parent, "--workflow-id", "WF-EP", "--requirement-id", "REQ-EP",
            "--artifact-profile", "PRD_ONLY", "--revision", "r2",
            "--procedure", paths["procedure"], "--handoff", paths["handoff"],
            "--finding-ledger", paths["findings"], "--repair-cycle", paths["repair"],
            "--cost-ledger", paths["cost"], "--final-gate", paths["gate"],
            "--consumer-report", paths["consumer"], "--decision-dir", paths["decisions"], "--out", out,
        ]

    def test_assembles_layered_episode_without_training_eligibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            out = root / "episode.json"
            result = run(self.args(paths, out))
            self.assertEqual(result["status"], "COMPLETE")
            self.assertFalse(result["trainingEligible"])
            episode = json.loads(out.read_text())
            self.assertEqual(episode["revision"], "r2")
            self.assertEqual(episode["findings"]["metrics"]["total"], 2)
            self.assertEqual(episode["repairs"]["rounds"], 1)
            self.assertEqual(episode["repairs"]["changedArtifacts"], ["Overview.html", "PRD_DELIVERY.md"])
            self.assertEqual(episode["consumerAcceptance"]["realCount"], 1)
            self.assertEqual(episode["humanAdjudication"]["status"], "RECORDED")
            self.assertEqual(episode["evidenceLayers"]["SOURCE_FACT"], sorted([str(paths["handoff"].resolve()), str((root / "decisions" / "D-1.json").resolve())]))
            self.assertIn(str(paths["cost"].resolve()), episode["evidenceLayers"]["MEASURED"])
            self.assertIn(str(paths["procedure"].resolve()), episode["evidenceLayers"]["DERIVED"])
            self.assertFalse(episode["trainingEligibility"]["eligible"])
            self.assertEqual(episode["trainingEligibility"]["status"], "BLOCKED")
            self.assertIn("D14_EPISODE_TRAINING_DISABLED", episode["trainingEligibility"]["reasons"])
            self.assertIn("Delivery Operating Procedure was created for r1", " ".join(episode["warnings"]))
            validated = run([VALIDATE, "--episode", out, "--verify-source-hashes"])
            self.assertEqual(validated["status"], "PASS")
            self.assertFalse(validated["trainingEligible"])

    def test_missing_optional_evidence_produces_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            out = root / "episode.json"
            base = self.args(paths, out)
            filtered = []
            skip = False
            for value in base:
                if skip:
                    skip = False
                    continue
                if value in {"--finding-ledger", "--consumer-report"}:
                    skip = True
                    continue
                filtered.append(value)
            # Keep required path arguments syntactically present but absent on disk.
            filtered.extend(["--finding-ledger", root / "missing-findings.json"])
            filtered = [str(item) for item in filtered]
            # Rebuild a clean argument list because required options must occur once.
            args = [
                str(BUILD), "--run-root", str(root), "--workflow-id", "WF-EP", "--requirement-id", "REQ-EP",
                "--artifact-profile", "PRD_ONLY", "--revision", "r2",
                "--procedure", str(paths["procedure"]), "--handoff", str(paths["handoff"]),
                "--finding-ledger", str(root / "missing-findings.json"), "--repair-cycle", str(paths["repair"]),
                "--cost-ledger", str(paths["cost"]), "--final-gate", str(paths["gate"]),
                "--decision-dir", str(paths["decisions"]), "--out", str(out),
            ]
            result = run(args)
            self.assertEqual(result["status"], "PARTIAL")
            episode = json.loads(out.read_text())
            self.assertGreaterEqual(len(episode["evidenceGaps"]), 2)
            self.assertEqual(episode["findings"]["status"], "UNAVAILABLE")

    def test_revision_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            handoff = json.loads(paths["handoff"].read_text())
            handoff["revision"] = "r1"
            paths["handoff"].write_text(json.dumps(handoff), encoding="utf-8")
            result = run(self.args(paths, root / "episode.json"), expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("revision does not match", result["error"])

    def test_hash_drift_blocks_episode_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            out = root / "episode.json"
            run(self.args(paths, out))
            cost = json.loads(paths["cost"].read_text())
            cost["revisions"].append({"revision": "r3", "auditStatuses": [], "sourceRefs": []})
            paths["cost"].write_text(json.dumps(cost), encoding="utf-8")
            result = run([VALIDATE, "--episode", out, "--verify-source-hashes"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("source hash drift" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
