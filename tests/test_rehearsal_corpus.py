import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILD = TOOLS / "build_rehearsal_corpus.py"
VALIDATE = TOOLS / "validate_rehearsal_corpus.py"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class RehearsalCorpusTests(unittest.TestCase):
    def fixture(self, root):
        def write(name, data):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        policy = write("gate-policy.json", {
            "schemaVersion": 1,
            "rules": [
                {
                    "ruleId": "G1.MUST.ROLES_PERMISSIONS", "gate": "G1", "severity": "BLOCKING",
                    "title": "Roles and permissions", "passCondition": "all roles and permissions are explicit",
                },
                {
                    "ruleId": "U1.NONBLOCKING.NOTE", "gate": "U1", "severity": "NON_BLOCKING",
                    "title": "Informational note", "passCondition": "note exists",
                },
            ],
        })
        findings = write("findings.json", {
            "schemaVersion": 1,
            "workflowId": "WF-RC",
            "currentRevision": "r2",
            "entries": [{
                "findingId": "F-1", "title": "Missing permission edge", "severity": "BLOCKING",
                "status": "resolved", "rootCauseId": "RC-1", "ruleIds": ["G1.MUST.ROLES_PERMISSIONS"],
                "firstSeenRevision": "r1", "lastSeenRevision": "r2",
            }],
            "metrics": {},
        })
        audit_result = write("audit/results/job.result.json", {
            "schemaVersion": 1, "workflowId": "WF-RC", "revision": "r2",
            "findings": [{
                "findingId": "A-1", "severity": "BLOCKING", "title": "AC not provable",
                "policyRuleIds": ["QA.ACCEPTANCE_EXECUTABLE"], "rootCauseId": "RC-A1",
            }],
        })
        tool_failure = write("tool-failures.json", {
            "schemaVersion": 1,
            "failures": [{
                "failureId": "TF-1", "toolId": "vibe-trading-reader", "toolDomain": "FINANCE_MARKET_RESEARCH",
                "operation": "READ", "rootCauseId": "RC-T1", "revision": "r2",
                "ruleIds": ["G1.MUST.ROLES_PERMISSIONS"],
                "negativeCondition": "Ask a finance-only tool to read a product-engineering document.",
                "expectedFailureKind": "TOOL_ROUTE_BLOCKED",
                "expectedFailure": "The router must block the cross-domain tool.",
            }],
        })
        manual = write("manual.json", {
            "schemaVersion": 1,
            "scenarios": [{
                "scenarioId": "M-1", "title": "Empty evidence must not pass",
                "ruleIds": ["G1.MUST.ROLES_PERMISSIONS"], "rootCauseIds": ["RC-M1"],
                "negativeCondition": "Remove all permission evidence.",
                "expectedFailureKind": "EVIDENCE_GAP", "replayMode": "EVALUATOR",
            }],
        })
        return policy, findings, audit_result.parent, tool_failure, manual

    def args(self, fixture, out, markdown=None):
        policy, findings, audit_dir, tool_failure, manual = fixture
        result = [
            BUILD, "--workflow-id", "WF-RC", "--revision", "r2",
            "--gate-policy", policy, "--finding-ledger", findings,
            "--audit-results-dir", audit_dir, "--tool-failure-report", tool_failure,
            "--manual-scenarios", manual, "--out", out,
        ]
        if markdown:
            result.extend(["--markdown-out", markdown])
        return result

    def test_builds_all_deterministic_source_types(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self.fixture(root)
            out = root / "corpus.json"
            markdown = root / "corpus.md"
            result = run(self.args(fixture, out, markdown))
            self.assertEqual(result["status"], "READY")
            corpus = json.loads(out.read_text())
            self.assertEqual(corpus["authority"]["releaseEligible"], False)
            self.assertEqual(corpus["authority"]["trainingEligible"], False)
            self.assertEqual(corpus["metrics"]["blockingRuleScenarios"], 1)
            self.assertEqual(corpus["metrics"]["historicalScenarios"], 2)
            self.assertEqual(corpus["metrics"]["toolFailureScenarios"], 1)
            self.assertEqual(corpus["metrics"]["manualScenarioCount"], 1)
            self.assertEqual(corpus["metrics"]["scenarioCount"], 5)
            types = {item["scenarioType"] for item in corpus["scenarios"]}
            self.assertTrue({"GATE_RULE_NEGATIVE", "HISTORICAL_FINDING_REPLAY", "AUDIT_FINDING_REPLAY", "TOOL_FAILURE_REPLAY", "MANUAL_SCENARIO"} <= types)
            self.assertIn("negative-test inputs only", markdown.read_text())
            validated = run([VALIDATE, "--corpus", out, "--verify-source-hashes"])
            self.assertEqual(validated["status"], "PASS")

    def test_policy_rule_negative_without_observed_failures_is_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            policy, findings, audit_dir, tool_failure, manual = self.fixture(root)
            out = root / "corpus.json"
            args = [
                BUILD, "--workflow-id", "WF-RC", "--revision", "r2",
                "--gate-policy", policy, "--finding-ledger", root / "missing-findings.json",
                "--audit-results-dir", root / "missing-audit", "--out", out,
            ]
            result = run(args)
            self.assertEqual(result["status"], "PARTIAL")
            corpus = json.loads(out.read_text())
            self.assertEqual(corpus["metrics"]["blockingRuleScenarios"], 1)
            self.assertGreaterEqual(len(corpus["evidenceGaps"]), 3)

    def test_validator_rejects_training_or_release_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self.fixture(root)
            out = root / "corpus.json"
            run(self.args(fixture, out))
            corpus = json.loads(out.read_text())
            corpus["authority"]["trainingEligible"] = True
            corpus["authority"]["releaseEligible"] = True
            corpus["authority"]["resultAuthority"] = "PASS"
            out.write_text(json.dumps(corpus), encoding="utf-8")
            result = run([VALIDATE, "--corpus", out], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("release or training eligibility" in error for error in result["errors"]))

    def test_source_hash_drift_blocks_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = self.fixture(root)
            out = root / "corpus.json"
            run(self.args(fixture, out))
            policy = fixture[0]
            policy.write_text(policy.read_text() + "\n", encoding="utf-8")
            result = run([VALIDATE, "--corpus", out, "--verify-source-hashes"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("source hash drift" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
