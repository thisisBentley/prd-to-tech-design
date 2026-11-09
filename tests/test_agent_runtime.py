import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "agent_runtime.py"


class AgentRuntimeTests(unittest.TestCase):
    def run_runtime(self, *args, expect=0):
        command = [sys.executable, str(RUNTIME), *map(str, args)]
        process = subprocess.run(command, text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def make_task(self, root, task_id="TASK-1", runtime="noop", command=None, role="prd-producer", mode="produce"):
        artifact = root / "input.md"
        artifact.write_text("frozen input\n", encoding="utf-8")
        task = {
            "schemaVersion": 1,
            "taskId": task_id,
            "workflowId": "WF-1",
            "stage": "delivery",
            "role": role,
            "objective": "execute one bounded delivery task",
            "inputs": [{"path": "input.md", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}],
            "constraints": ["do not invent facts"],
            "expectedOutputs": ["result.json"],
            "reviewMode": mode,
            "writeScope": ["result.json"],
            "readOnlyFrozenInputs": mode != "produce",
            "runtime": runtime,
            "timeoutSeconds": 5,
        }
        if command is not None:
            task["command"] = command
        path = root / f"{task_id}.task.json"
        path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def result_file(self, root):
        path = root / "result.json"
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "status": "DONE",
            "outputs": [{"path": "PRD.md", "kind": "PRD"}],
        }), encoding="utf-8")
        return path

    def test_noop_spawn_and_collect_replays_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            task = self.make_task(root)
            spawned = self.run_runtime("spawn", "--run-root", root, "--task", task)
            self.assertEqual(spawned["status"], "SPAWNED")
            self.assertNotEqual(spawned["contextId"], "")
            result = self.result_file(root)
            collected = self.run_runtime("collect", "--run-root", root, "--task-id", "TASK-1", "--result", result)
            self.assertEqual(collected["status"], "SUCCEEDED")
            self.assertTrue(collected["structuredResultSha256"])
            record = json.loads(Path(collected["record"]).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "SUCCEEDED")
            self.assertEqual(record["taskManifestSha256"], hashlib.sha256(task.read_bytes()).hexdigest())
            self.assertEqual(record["structuredResultSha256"], collected["structuredResultSha256"])

    def test_process_executes_structured_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            self.result_file(root)
            command = {"argv": [sys.executable, "-c", "pass"], "resultPath": "result.json"}
            task = self.make_task(root, runtime="process", command=command)
            executed = self.run_runtime("spawn", "--run-root", root, "--task", task, "--execute")
            self.assertEqual(executed["status"], "SUCCEEDED")
            record = json.loads(Path(executed["record"]).read_text(encoding="utf-8"))
            self.assertEqual(record["exitCode"], 0)
            self.assertTrue(Path(record["transcriptPath"]).exists())

    def test_codex_adapter_uses_argv_and_collects_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            self.result_file(root)
            sentinel = root / "sentinel.txt"
            command = {"argv": [sys.executable, "-c", "import pathlib; pathlib.Path('sentinel.txt').write_text('ok')"], "resultPath": "result.json"}
            task = self.make_task(root, runtime="codex", command=command)
            executed = self.run_runtime("spawn", "--run-root", root, "--task", task, "--execute")
            self.assertEqual(executed["status"], "SUCCEEDED")
            self.assertTrue(sentinel.exists())
            record = json.loads(Path(executed["record"]).read_text(encoding="utf-8"))
            self.assertEqual(record["runtime"], "codex")

    def test_invalid_structured_result_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            invalid = root / "result.json"
            invalid.write_text(json.dumps({"schemaVersion": 1, "status": "DONE"}), encoding="utf-8")
            command = {"argv": [sys.executable, "-c", "pass"], "resultPath": "result.json"}
            task = self.make_task(root, runtime="process", command=command)
            executed = self.run_runtime("spawn", "--run-root", root, "--task", task, "--execute", expect=1)
            self.assertEqual(executed["status"], "FAILED")
            record = json.loads(Path(executed["record"]).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "FAILED")

    def test_timeout_writes_failed_audit_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            self.result_file(root)
            command = {"argv": [sys.executable, "-c", "import time; time.sleep(1)"], "resultPath": "result.json"}
            task = self.make_task(root, runtime="process", command=command)
            task.write_text(task.read_text(encoding="utf-8").replace('"timeoutSeconds": 5', '"timeoutSeconds": 0.1'), encoding="utf-8")
            executed = self.run_runtime("spawn", "--run-root", root, "--task", task, "--execute", expect=1)
            self.assertEqual(executed["status"], "FAILED")
            record = json.loads(Path(executed["record"]).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "FAILED")
            self.assertIn("timeout", record["error"])

    def test_frozen_input_hash_mismatch_fails_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            task = self.make_task(root)
            (root / "input.md").write_text("mutated\n", encoding="utf-8")
            failed = self.run_runtime("spawn", "--run-root", root, "--task", task, expect=1)
            self.assertEqual(failed["status"], "FAIL")

    def test_reviewer_isolation_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            task = self.make_task(root, role="delivery-reviewer", mode="independent-review")
            data = json.loads(task.read_text(encoding="utf-8"))
            data["readOnlyFrozenInputs"] = False
            task.write_text(json.dumps(data), encoding="utf-8")
            failed = self.run_runtime("spawn", "--run-root", root, "--task", task, expect=1)
            self.assertEqual(failed["status"], "FAIL")
            self.assertTrue(any("readOnlyFrozenInputs" in error for error in failed["errors"]))

    def test_reviewer_process_runtime_executes_with_isolated_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            self.result_file(root)
            producer_task = self.make_task(root, task_id="PRODUCER-1")
            producer = self.run_runtime("spawn", "--run-root", root, "--task", producer_task)
            reviewer_task = self.make_task(
                root,
                task_id="REVIEWER-1",
                runtime="process",
                command={"argv": [sys.executable, "-c", "pass"], "resultPath": "result.json"},
                role="delivery-reviewer",
                mode="independent-review",
            )
            reviewer = self.run_runtime("spawn", "--run-root", root, "--task", reviewer_task, "--execute")
            self.assertEqual(reviewer["status"], "SUCCEEDED")
            self.assertNotEqual(producer["contextId"], reviewer["contextId"])
            producer_record = json.loads((root / ".agents" / "runtime" / "PRODUCER-1.json").read_text(encoding="utf-8"))
            reviewer_record = json.loads((root / ".agents" / "runtime" / "REVIEWER-1.json").read_text(encoding="utf-8"))
            self.assertNotEqual(producer_record["contextId"], reviewer_record["contextId"])
            self.assertEqual(reviewer_record["status"], "SUCCEEDED")
            self.assertTrue(json.loads(reviewer_task.read_text(encoding="utf-8"))["readOnlyFrozenInputs"])

    def test_collect_failure_and_cancel_are_auditable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            task = self.make_task(root)
            self.run_runtime("spawn", "--run-root", root, "--task", task)
            missing = self.run_runtime("collect", "--run-root", root, "--task-id", "TASK-1", expect=1)
            self.assertEqual(missing["status"], "FAILED")
            cancelled_task = self.make_task(root, task_id="TASK-CANCEL")
            self.run_runtime("spawn", "--run-root", root, "--task", cancelled_task)
            cancelled = self.run_runtime("collect", "--run-root", root, "--task-id", "TASK-CANCEL", "--cancel")
            self.assertEqual(cancelled["status"], "CANCELLED")
            record = json.loads(Path(cancelled["record"]).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
