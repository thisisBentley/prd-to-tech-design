import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
WORKER = ROOT / SCRIPTS / "codex_worker.py"
FAKE = ROOT / SCRIPTS / "fake_codex.py"


class CodexWorkerTests(unittest.TestCase):
    def run_worker(self, root, task):
        manifest = root / "task.json"
        manifest.write_text(json.dumps(task), encoding="utf-8")
        result = root / ".agents" / "results" / "result.json"
        review = root / ".agents" / "reviews" / "review.json"
        artifact = root / ".agents" / "artifacts" / "PRD_DELIVERY.md"
        transcript = root / ".agents" / "runtime" / "transcript.log"
        argv_audit = root / "argv.json"
        (root / "input.md").write_text("input\n", encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "AI_NATIVE_TASK_MANIFEST": str(manifest),
            "AI_NATIVE_RESULT_PATH": str(result),
            "AI_NATIVE_REVIEW_PATH": str(review),
            "AI_NATIVE_ARTIFACT_PATH": str(artifact),
            "AI_NATIVE_TRANSCRIPT_PATH": str(transcript),
            "AI_NATIVE_RUN_ROOT": str(root),
            "AI_NATIVE_TIMEOUT": "5",
            "AI_NATIVE_FAKE_CODEX_ARGV": str(argv_audit),
            "AI_NATIVE_FAKE_CODEX_RESULT": json.dumps({"schemaVersion": 1, "status": "SUCCEEDED", "outputs": [{"path": str(artifact)}]}),
        })
        process = subprocess.run([sys.executable, str(WORKER), "--codex", str(FAKE)], env=env, text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return result, review, artifact, transcript, argv_audit

    def test_codex_boundary_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            task = {
                "schemaVersion": 1, "taskId": "CODEX-1", "workflowId": "WF", "stage": "delivery", "role": "prd-producer",
                "objective": "produce PRD", "inputs": [{"path": "input.md", "sha256": hashlib.sha256(b"input\n").hexdigest()}],
                "constraints": ["no invented facts"], "expectedOutputs": ["PRD_DELIVERY.md"],
                "reviewMode": "produce", "readOnlyFrozenInputs": False, "runtime": "codex",
            }
            result, review, artifact, transcript, argv_audit = self.run_worker(root, task)
            argv = json.loads(argv_audit.read_text(encoding="utf-8"))
            self.assertIn("exec", argv)
            self.assertIn("--ephemeral", argv)
            self.assertIn("--skip-git-repo-check", argv)
            self.assertIn("--sandbox", argv)
            self.assertIn("read-only", argv)
            self.assertIn("--output-last-message", argv)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(payload["status"], "SUCCEEDED")
            self.assertTrue(payload["outputs"])
            self.assertTrue(transcript.exists())

    def test_invalid_codex_result_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            task = {
                "schemaVersion": 1, "taskId": "CODEX-2", "workflowId": "WF", "stage": "delivery", "role": "prd-producer",
                "objective": "produce PRD", "inputs": [{"path": "input.md", "sha256": hashlib.sha256(b"input\n").hexdigest()}],
                "constraints": ["no invented facts"], "expectedOutputs": ["PRD_DELIVERY.md"],
                "reviewMode": "produce", "readOnlyFrozenInputs": False, "runtime": "codex",
            }
            manifest = root / "task.json"; manifest.write_text(json.dumps(task), encoding="utf-8")
            result = root / "result.json"; transcript = root / "transcript.log"
            env = os.environ.copy()
            env.update({
                "AI_NATIVE_TASK_MANIFEST": str(manifest), "AI_NATIVE_RESULT_PATH": str(result),
                "AI_NATIVE_REVIEW_PATH": str(root / "review.json"), "AI_NATIVE_ARTIFACT_PATH": str(root / "artifact.md"),
                "AI_NATIVE_TRANSCRIPT_PATH": str(transcript), "AI_NATIVE_RUN_ROOT": str(root), "AI_NATIVE_TIMEOUT": "5",
                "AI_NATIVE_FAKE_CODEX_RESULT": json.dumps({"status": "SUCCEEDED"}),
            })
            process = subprocess.run([sys.executable, str(WORKER), "--codex", str(FAKE)], env=env, text=True, capture_output=True)
            self.assertEqual(process.returncode, 3)
            self.assertIn("structured envelope", process.stderr)


if __name__ == "__main__":
    unittest.main()
