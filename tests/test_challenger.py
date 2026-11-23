import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
RUNNER = TOOLS / "run_challenger.py"
FIXTURE = ROOT / "tests" / "fixtures" / "challenger" / "fake_challenger_worker.py"


def run(argv, expect=0, env=None):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True, env=env)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class ChallengerTests(unittest.TestCase):
    def fixture(self, root):
        def write(name, data):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        scenarios = []
        for index, kind in enumerate(["RULE_NOT_PROVEN", "FINDING_REOBSERVED", "TOOL_ROUTE_BLOCKED"], 1):
            scenarios.append({
                "scenarioId": f"RS-{index:016x}",
                "scenarioType": "GATE_RULE_NEGATIVE",
                "title": f"Scenario {index}",
                "classification": "DERIVED_FROM_NORMATIVE",
                "sourceRefs": [{"kind": "GATE_POLICY", "path": str(root / "gate-policy.json"), "sha256": "a" * 64}],
                "ruleIds": [f"G1.RULE-{index}"],
                "rootCauseIds": [],
                "revisionRefs": [],
                "negativeCondition": "remove evidence",
                "expectedFailureSignal": {"kind": kind, "description": "the failure signal must be observed"},
                "forbiddenOutcomes": ["RELEASE_EVIDENCE_PROMOTION", "TRAINING_PROMOTION"],
                "replay": {"mode": "AUDIT_JOB", "frozen": True, "reproducible": True},
            })
        corpus = write("corpus.json", {
            "schemaVersion": 1,
            "corpusId": "RC-0123456789abcdef",
            "workflowId": "WF-CHAL",
            "revision": "r2",
            "status": "READY",
            "authority": {"purpose": "NEGATIVE_TEST_INPUT", "resultAuthority": "NONE", "releaseEligible": False, "trainingEligible": False},
            "sources": [{"kind": "GATE_POLICY", "path": str(root / "gate-policy.json"), "sha256": "a" * 64}],
            "scenarios": scenarios,
            "coverage": {"policyRules": 3, "coveredPolicyRules": 3, "uncoveredPolicyRules": [], "historicalFindings": 0, "toolFailures": 0, "manualScenarios": 0},
            "metrics": {"sourceCount": 1, "scenarioCount": 3, "blockingRuleScenarios": 3, "historicalScenarios": 0, "toolFailureScenarios": 0, "manualScenarioCount": 0},
            "evidenceGaps": [],
            "warnings": [],
            "createdAt": "2026-11-23T00:00:00+00:00",
        })
        write("gate-policy.json", {"schemaVersion": 1, "rules": [{"ruleId": f"G1.RULE-{i}", "severity": "BLOCKING"} for i in range(1, 4)]})
        artifact_root = root / "candidate"
        artifact_root.mkdir()
        (artifact_root / "PRD_DELIVERY.md").write_text("# Candidate\n", encoding="utf-8")
        return corpus, artifact_root

    def args(self, corpus, artifact_root, out):
        return [
            RUNNER, "--corpus", corpus, "--run-root", out.parent,
            "--artifact-root", artifact_root, "--out", out,
            "--worker", sys.executable, FIXTURE,
        ]

    def test_all_detected_without_release_or_training_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus, artifacts = self.fixture(root)
            out = root / "challenge.json"
            result = run(self.args(corpus, artifacts, out))
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["outcome"], "ALL_DETECTED")
            report = json.loads(out.read_text())
            self.assertEqual(report["authority"]["resultAuthority"], "NONE")
            self.assertFalse(report["authority"]["releaseEligible"])
            self.assertFalse(report["authority"]["trainingEligible"])
            self.assertEqual(report["metrics"]["scenarios"], 3)
            self.assertEqual(report["metrics"]["detected"], 3)
            self.assertEqual(report["artifactSnapshotSha256Before"], report["artifactSnapshotSha256After"])
            self.assertEqual([item["status"] for item in report["scenarioResults"]], ["DETECTED"] * 3)

    def test_missed_scenario_is_gaps_found_not_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus, artifacts = self.fixture(root)
            out = root / "challenge.json"
            env = dict(os.environ, FAKE_CHALLENGER_MISSED="1")
            result = run(self.args(corpus, artifacts, out), env=env)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["outcome"], "GAPS_FOUND")
            report = json.loads(out.read_text())
            self.assertEqual(report["metrics"]["missed"], 3)

    def test_candidate_mutation_blocks_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus, artifacts = self.fixture(root)
            out = root / "challenge.json"
            env = dict(os.environ, FAKE_CHALLENGER_MUTATE="1")
            result = run(self.args(corpus, artifacts, out), expect=1, env=env)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["outcome"], "BLOCKED")
            report = json.loads(out.read_text())
            self.assertTrue(any("snapshot changed" in error for error in report["errors"]))
            self.assertNotEqual(report["artifactSnapshotSha256Before"], report["artifactSnapshotSha256After"])

    def test_incomplete_and_error_are_not_all_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus, artifacts = self.fixture(root)
            out = root / "challenge.json"
            env = dict(os.environ, FAKE_CHALLENGER_INCOMPLETE="1")
            result = run(self.args(corpus, artifacts, out), env=env)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["outcome"], "INCOMPLETE")
            env = dict(os.environ, FAKE_CHALLENGER_ERROR="1")
            result = run(self.args(corpus, artifacts, root / "challenge-error.json"), expect=1, env=env)
            self.assertEqual(result["status"], "BLOCKED")

    def test_corpus_authority_cannot_enable_release_or_training(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus, artifacts = self.fixture(root)
            data = json.loads(corpus.read_text())
            data["authority"]["releaseEligible"] = True
            corpus.write_text(json.dumps(data), encoding="utf-8")
            out = root / "challenge.json"
            result = run(self.args(corpus, artifacts, out), expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            report = json.loads(out.read_text())
            self.assertIn("Rehearsal Corpus authority is invalid", report["errors"])


if __name__ == "__main__":
    unittest.main()
