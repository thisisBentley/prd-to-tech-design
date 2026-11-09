import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tools" / "m1_semantic_worker.py"
FAKE = ROOT / "tools" / "fake_codex.py"


class M1SemanticWorkerTests(unittest.TestCase):
    def run_worker(self, root, task, fake_result, expect=0):
        manifest = root / "task.json"
        manifest.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "AI_NATIVE_TASK_MANIFEST": str(manifest),
            "AI_NATIVE_RUN_ROOT": str(root),
            "AI_NATIVE_RESULT_PATH": str(root / "result.json"),
            "AI_NATIVE_ARTIFACT_PATH": str(root / "PRD_DELIVERY.md"),
            "AI_NATIVE_REVIEW_PATH": str(root / "review.json"),
            "AI_NATIVE_TRANSCRIPT_PATH": str(root / "transcript.log"),
            "AI_NATIVE_CONTEXT_ID": "context-delivery-reviewer-fake",
            "AI_NATIVE_TARGET_REVISION": "r1",
            "AI_NATIVE_TIMEOUT": "5",
            "AI_NATIVE_FAKE_CODEX_RESULT": json.dumps(fake_result, ensure_ascii=False),
        })
        process = subprocess.run(
            [sys.executable, str(WORKER), "--codex", str(FAKE), "--timeout", "5"],
            env=env, text=True, capture_output=True, cwd=ROOT,
        )
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return process

    def producer_task(self, root):
        input_path = root / "requirement.md"
        input_path.write_text("# Requirement\n\nBuild expense submission with approval.\n", encoding="utf-8")
        return {
            "schemaVersion": 1,
            "taskId": "PRD-PRODUCE",
            "workflowId": "WF-M1",
            "stage": "DELIVERY_PRODUCER",
            "role": "prd-producer",
            "objective": "produce semantic PRD",
            "inputs": [{"path": "requirement.md", "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()}],
            "constraints": ["Use only supplied facts."],
            "expectedOutputs": ["PRD_DELIVERY.md"],
            "reviewMode": "produce",
            "readOnlyFrozenInputs": False,
            "runtime": "codex",
        }

    def valid_review(self):
        return {
            "schemaVersion": 1,
            "reviewerRole": "delivery-reviewer",
            "verdict": "RETURNED",
            "completionStatus": "complete",
            "blockingCount": 1,
            "evidenceRefs": ["PRD_DELIVERY.md"],
            "checks": [{"checkId": "coverage", "status": "failed", "evidenceRefs": ["PRD_DELIVERY.md"], "observed": "missing approval", "expected": "approval covered"}],
            "findings": [{
                "findingId": "F-001", "severity": "BLOCKING", "title": "Approval missing",
                "evidenceRefs": ["PRD_DELIVERY.md"], "impact": "Cannot implement approval", "closeCondition": "Add approval FR",
                "owner": "prd-producer", "rootCauseId": "missing-approval", "repairClass": "SEMANTIC",
                "expectedInvariant": "PRD covers every supplied business rule", "regressionTests": ["semantic recheck"],
            }],
        }

    def test_producer_materializes_frozen_prd(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.producer_task(root)
            self.run_worker(root, task, {
                "schemaVersion": 1, "status": "SUCCEEDED",
                "outputs": [{"path": "PRD_DELIVERY.md", "kind": "PRD"}],
                "prdMarkdown": "# PRD_DELIVERY\n\n## Functional Requirements\n\n- FR-001: Expense submission with approval.\n",
                "evidenceRefs": [],
            })
            payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
            artifact = root / "PRD_DELIVERY.md"
            self.assertTrue(artifact.exists())
            self.assertEqual(payload["prdArtifactPath"], str(artifact.resolve()))
            self.assertEqual(payload["prdArtifactSha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())

    def test_review_result_is_canonicalized_and_contract_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "PRD_DELIVERY.md"
            input_path.write_text("# PRD\n", encoding="utf-8")
            task = {
                "schemaVersion": 1, "taskId": "DELIVERY-REVIEW", "workflowId": "WF-M1", "stage": "DELIVERY_REVIEWER",
                "role": "delivery-reviewer", "objective": "review PRD", "inputs": [{"path": "PRD_DELIVERY.md", "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()}],
                "constraints": ["read-only"], "expectedOutputs": ["review-result"], "reviewMode": "independent-review",
                "readOnlyFrozenInputs": True, "runtime": "codex",
            }
            self.run_worker(root, task, {
                "schemaVersion": 1, "status": "SUCCEEDED",
                "outputs": [{"path": "review-result", "kind": "review-result"}],
                "reviewResult": self.valid_review(),
                "evidenceRefs": [],
            })
            review = json.loads((root / "review.json").read_text(encoding="utf-8"))
            payload = json.loads((root / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(review["verdict"], "RETURNED")
            self.assertEqual(review["reviewerRole"], "delivery-reviewer")
            self.assertEqual(review["blockingCount"], 1)
            self.assertEqual(payload["verdict"], "RETURNED")
            validator = ROOT / "tools" / "validate_agent_contracts.py"
            process = subprocess.run([sys.executable, str(validator), str(root / "review.json")], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_invalid_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "PRD_DELIVERY.md"
            input_path.write_text("# PRD\n", encoding="utf-8")
            task = {
                "schemaVersion": 1, "taskId": "QA-RED-TEAM", "workflowId": "WF-M1", "stage": "DELIVERY_REVIEWER",
                "role": "qa-red-team", "objective": "challenge PRD", "inputs": [{"path": "PRD_DELIVERY.md", "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()}],
                "constraints": ["read-only"], "expectedOutputs": ["review-result"], "reviewMode": "independent-review",
                "readOnlyFrozenInputs": True, "runtime": "codex",
            }
            bad = self.valid_review()
            bad["verdict"] = "ACCEPTED"
            self.run_worker(root, task, {
                "schemaVersion": 1, "status": "SUCCEEDED",
                "outputs": [{"path": "review-result", "kind": "review-result"}],
                "reviewResult": bad,
            }, expect=4)


if __name__ == "__main__":
    unittest.main()
