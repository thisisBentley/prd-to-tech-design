import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
AUDIT = TOOLS / "audit_evaluation_integrity.py"
ATTRIBUTION = TOOLS / "analyze_capability_attribution.py"
RUN_AUDIT = TOOLS / "audit_evaluation_run.py"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class EvaluationIntegrityTests(unittest.TestCase):
    def fixture(self, root):
        issue = root / "issues" / "SAMPLE-1"
        (issue / "README.md").parent.mkdir(parents=True)
        (issue / "README.md").write_text("summary", encoding="utf-8")
        tasks = root / "tasks.jsonl"
        task = {
            "schemaVersion": 1,
            "goldenTaskId": "GOLD-1",
            "taskVersion": "v1",
            "taskId": "TASK-1",
            "sampleId": "SAMPLE-1",
            "groupId": "G-1",
            "split": "validation",
            "capabilityMode": "REVIEW",
            "taskType": "REVIEW_TASK",
            "prompt": "根据客户接口契约、PRD、Overview 和 Prototype，检查字段来源",
            "rubric": {"mustInclude": ["FINDING"], "mustNotDo": ["invent"], "evidenceRefs": ["README.md"], "requiresExplicitUncertainty": True},
            "sourceApprovalStatus": "PENDING_MANUAL_APPROVAL",
            "usageStatus": "HELDOUT_ONLY_NOT_TRAINING",
        }
        tasks.write_text(json.dumps(task) + "\n", encoding="utf-8")
        policy = root / "policy.json"
        policy.write_text(json.dumps({
            "schemaVersion": 1,
            "artifactTypes": {
                "CUSTOMER_CONTRACT": {"pathPatterns": ["contract|契约|接口文档"]},
                "PRD": {"pathPatterns": ["PRD"]},
                "OVERVIEW": {"pathPatterns": ["Overview"]},
                "PROTOTYPE": {"pathPatterns": ["Prototype"]},
            },
            "scopeRules": [{
                "ruleId": "REVIEW_ORIGINAL_ARTIFACTS",
                "taskTypes": ["REVIEW_TASK"],
                "promptAll": ["根据客户接口契约", "PRD", "Overview", "Prototype"],
                "requiredArtifactTypes": ["CUSTOMER_CONTRACT", "PRD", "OVERVIEW", "PROTOTYPE"],
            }],
        }), encoding="utf-8")
        return tasks, policy, issue.parent

    def test_detects_task_evidence_scope_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tasks, policy, issue_root = self.fixture(root)
            out = root / "report.json"
            result = run([AUDIT, "--tasks", tasks, "--issue-root", issue_root, "--policy", policy, "--out", out, "--strict"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["invalidTaskIds"], ["GOLD-1"])

    def test_capability_attribution_holds_training(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tasks, policy, issue_root = self.fixture(root)
            integrity = root / "integrity.json"
            run([AUDIT, "--tasks", tasks, "--issue-root", issue_root, "--policy", policy, "--out", integrity])
            gaps = root / "gaps.json"
            gaps.write_text(json.dumps({"capabilities": {"REVIEW": {"sampleCount": 4, "riskCodes": ["SEMANTIC_RECALL_GAP"], "stableAcrossSplits": True}}}), encoding="utf-8")
            out = root / "attribution.json"
            result = run([ATTRIBUTION, "--integrity", integrity, "--historical-integrity", integrity, "--capability-gap", gaps, "--out", out])
            self.assertEqual(result["status"], "BLOCKED_BY_TASK_INTEGRITY")
            self.assertEqual(result["decision"]["modelParameterGap"], "NOT_PROVEN")
            self.assertEqual(result["decision"]["training"], "HOLD")

    def test_evaluation_run_audit_blocks_missing_predictions_and_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tasks, policy, issue_root = self.fixture(root)
            integrity = root / "integrity.json"
            run([AUDIT, "--tasks", tasks, "--issue-root", issue_root, "--policy", policy, "--out", integrity])
            predictions = root / "predictions"
            predictions.mkdir()
            for split in ["validation", "test"]:
                (predictions / f"b0-{split}.jsonl").write_text(json.dumps({"goldenTaskId": "GOLD-1"}) + "\n", encoding="utf-8")
                (predictions / f"b1-{split}.jsonl").write_text(json.dumps({"goldenTaskId": "GOLD-1"}) + "\n", encoding="utf-8")
                (predictions / f"b2-{split}.jsonl").write_text(json.dumps({"goldenTaskId": "GOLD-1"}) + "\n", encoding="utf-8")
            out = root / "run-audit.json"
            result = run([
                RUN_AUDIT,
                "--integrity", integrity,
                "--tasks", tasks,
                "--predictions-dir", predictions,
                "--runtime-blocker", "METAL_UNAVAILABLE",
                "--out", out,
                "--strict",
            ], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["closureEligible"])


if __name__ == "__main__":
    unittest.main()
