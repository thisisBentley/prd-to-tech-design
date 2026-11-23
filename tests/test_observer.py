import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILD = TOOLS / "build_observer_report.py"
VALIDATE = TOOLS / "validate_observer_report.py"

def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)

class ObserverTests(unittest.TestCase):
    def fixture(self, root, with_challenger=True):
        def write(name, data):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        episode = write("episode.json", {
            "schemaVersion": 1, "episodeId": "EP-0123456789abcdef",
            "workflowId": "WF-OBS", "requirementId": "REQ-OBS",
            "artifactProfile": "PRD_ONLY", "revision": "r2", "status": "PARTIAL",
            "objective": "Deliver a safe export",
            "findings": {"metrics": {"total": 2, "openBlocking": 1}, "status": "AVAILABLE"},
            "evidenceLayers": {"SOURCE_FACT": [], "MEASURED": [], "DERIVED": [], "REFERENCE": [], "INFERENCE": []}
        })
        findings = write("findings.json", {
            "schemaVersion": 1, "workflowId": "WF-OBS", "currentRevision": "r2",
            "entries": [
                {"findingId": "F-1", "rootCauseId": "RC-1", "severity": "BLOCKING", "status": "open", "ruleIds": ["G1.RULE"], "repairAttempts": 2},
                {"findingId": "F-2", "rootCauseId": "RC-1", "severity": "BLOCKING", "status": "resolved", "ruleIds": ["G1.RULE"], "repairAttempts": 1},
            ],
            "metrics": {"total": 2, "openBlocking": 1}
        })
        repair = write("repair.json", {
            "schemaVersion": 1, "workflowId": "WF-OBS", "finalRevision": "r2", "status": "AUDIT_PASS",
            "rounds": []
        })
        cost = write("cost.json", {
            "schemaVersion": 1, "workflowId": "WF-OBS", "finalRevision": "r2",
            "metricsAvailability": "PARTIAL", "metrics": {"repairRounds": 0, "estimatedTranscriptTokens": 12}
        })
        corpus = write("corpus.json", {
            "schemaVersion": 1, "corpusId": "RC-0123456789abcdef",
            "workflowId": "WF-OBS", "revision": "r2", "status": "PARTIAL",
            "authority": {"purpose": "NEGATIVE_TEST_INPUT", "resultAuthority": "NONE", "releaseEligible": False, "trainingEligible": False},
            "scenarios": [{"scenarioId": "RS-0123456789abcdef", "scenarioType": "GATE_RULE_NEGATIVE"}]
        })
        challenger = None
        if with_challenger:
            challenger = write("challenger.json", {
                "schemaVersion": 1, "challengeRunId": "CHAL-0123456789abcdef",
                "workflowId": "WF-OBS", "revision": "r2", "corpusId": "RC-0123456789abcdef",
                "corpusSha256": "a" * 64, "status": "COMPLETE", "outcome": "GAPS_FOUND",
                "authority": {"readOnly": True, "mayModifyArtifacts": False, "resultAuthority": "NONE", "releaseEligible": False, "trainingEligible": False},
                "scenarioResults": [], "metrics": {"scenarios": 3, "detected": 2, "missed": 1, "incomplete": 0, "errors": 0, "elapsedMs": 1},
                "startedAt": "2026-11-23T00:00:00Z", "finishedAt": "2026-11-23T00:00:01Z", "createdAt": "2026-11-23T00:00:01Z"
            })
        return episode, findings, repair, cost, corpus, challenger

    def args(self, paths, out):
        episode, findings, repair, cost, corpus, challenger = paths
        args = [
            BUILD, "--episode", episode, "--finding-ledger", findings,
            "--repair-cycle", repair, "--cost-ledger", cost, "--corpus", corpus, "--out", out
        ]
        if challenger:
            args.extend(["--challenger-run", challenger])
        return args

    def test_builds_observer_with_root_cause_and_challenger_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            out = root / "observer.json"
            result = run(self.args(paths, out))
            self.assertEqual(result["status"], "PARTIAL")
            report = json.loads(out.read_text())
            self.assertEqual(report["authority"]["resultAuthority"], "NONE")
            self.assertFalse(report["authority"]["releaseEligible"])
            self.assertFalse(report["authority"]["trainingEligible"])
            self.assertFalse(report["authority"]["causalClaims"])
            self.assertEqual(report["metrics"]["rootCauses"], 1)
            self.assertEqual(report["metrics"]["openBlockingRootCauses"], 1)
            self.assertEqual(report["metrics"]["challengerMissed"], 1)
            recommendation_ids = {item["recommendationId"] for item in report["recommendations"]}
            self.assertIn("REVIEW_ROOT_CAUSE", recommendation_ids)
            self.assertIn("REVIEW_CHALLENGER_GAP", recommendation_ids)
            self.assertTrue(all(item["changeSetRequired"] is False for item in report["recommendations"]))
            validated = run([VALIDATE, "--report", out, "--verify-source-hashes"])
            self.assertEqual(validated["status"], "PASS")

    def test_missing_challenger_is_partial_and_recommends_real_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root, with_challenger=False)
            out = root / "observer.json"
            result = run(self.args(paths, out))
            self.assertEqual(result["status"], "PARTIAL")
            report = json.loads(out.read_text())
            self.assertIn("CHALLENGER_RUN:MISSING", report["evidenceGaps"])
            self.assertIn("RUN_REAL_CASE", {item["recommendationId"] for item in report["recommendations"]})

    def test_source_hash_drift_blocks_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            out = root / "observer.json"
            run(self.args(paths, out))
            paths[1].write_text(paths[1].read_text() + "\n", encoding="utf-8")
            result = run([VALIDATE, "--report", out, "--verify-source-hashes"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("source hash drift" in error for error in result["errors"]))

    def test_validator_rejects_causal_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            out = root / "observer.json"
            run(self.args(paths, out))
            report = json.loads(out.read_text())
            report["authority"]["causalClaims"] = True
            out.write_text(json.dumps(report), encoding="utf-8")
            result = run([VALIDATE, "--report", out], expect=1)
            self.assertEqual(result["status"], "BLOCKED")

if __name__ == "__main__":
    unittest.main()
