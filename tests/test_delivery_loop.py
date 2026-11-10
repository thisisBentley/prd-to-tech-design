import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "orchestrate.py"
LOOP = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "delivery_loop.py"


class DeliveryLoopTests(unittest.TestCase):
    def run_cli(self, command, *args, expect=0):
        executable = command.resolve()
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        if process.stdout.strip():
            return json.loads(process.stdout)
        return {}

    def prepare(self, root):
        plan = root / "plan.json"
        requirement = root / "requirement.md"
        requirement.write_text("# Requirement\n\nPRD_ONLY smoke requirement.\n", encoding="utf-8")
        self.run_cli(ORCH, "init", "--run-root", root, "--workflow-id", "WF-LOOP", "--requirement-name", "Loop Demo", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
        self.run_cli(ORCH, "build-delivery-plan", "--run-root", root, "--out", plan)
        return plan, requirement

    def test_factory_builds_frozen_dependency_bound_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            self.run_cli(ORCH, "delivery-task-start", "--run-root", root, "--plan", plan, "--task-id", "DECISION-READINESS")
            decision = root / "decision-context.json"
            decision.write_text(json.dumps({"ready": True}), encoding="utf-8")
            self.run_cli(ORCH, "delivery-task-complete", "--run-root", root, "--plan", plan, "--task-id", "DECISION-READINESS", "--result", decision)
            factory = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "agent_task_factory.py"
            created = self.run_cli(factory, "--run-root", root, "--plan", plan, "--task-id", "PRD-PRODUCE", "--requirement", requirement)
            task = json.loads(Path(created["task"]).read_text(encoding="utf-8"))
            paths = [item["path"] for item in task["inputs"]]
            self.assertIn("requirement.md", paths)
            self.assertIn("decision-context.json", paths)
            self.assertEqual(task["taskId"], "PRD-PRODUCE")
            self.assertFalse(task["readOnlyFrozenInputs"])

    def test_capability_context_validator_accepts_existing_capability(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            capability = root / "capability.json"
            prd = root / "PRD_DELIVERY.md"
            out = root / "capability-check.json"
            capability.write_text(json.dumps({"schemaVersion": 1, "capabilityId": "cap.scene-intent", "canonicalName": "场景意图", "status": "EXISTING", "knownAliases": ["场景意图识别"], "sourceRefs": ["history://scene-intent"], "confidence": "HIGH", "decisionStatus": "CONFIRMED"}), encoding="utf-8")
            prd.write_text("# PRD\n\n复用已有能力：场景意图。\n", encoding="utf-8")
            tool = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "validate_capability_context.py"
            result = self.run_cli(tool, "--capability", capability, "--prd", prd, "--out", out)
            self.assertEqual(result["status"], "PASS")

    def test_factory_carries_capability_and_provenance_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            context_dir = root / ".agents" / "context"; context_dir.mkdir(parents=True)
            (context_dir / "capability-context.json").write_text(json.dumps({"schemaVersion": 1, "capabilityId": "cap.scene-intent", "canonicalName": "场景意图", "status": "EXISTING", "sourceRefs": ["history-1"], "confidence": "HIGH", "decisionStatus": "CONFIRMED"}), encoding="utf-8")
            (context_dir / "source-provenance.json").write_text(json.dumps({"schemaVersion": 1, "sourceId": "history-1", "sourceType": "HISTORY", "pathOrRef": "history-1", "sha256": "a" * 64, "authorityDomain": "BUSINESS"}), encoding="utf-8")
            factory = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "agent_task_factory.py"
            created = self.run_cli(factory, "--run-root", root, "--plan", plan, "--task-id", "DECISION-READINESS", "--requirement", requirement)
            task = json.loads(Path(created["task"]).read_text(encoding="utf-8"))
            self.assertIn(".agents/context/capability-context.json", [item["path"] for item in task["inputs"]])
            self.assertIn(".agents/context/source-provenance.json", [item["path"] for item in task["inputs"]])

    def test_factory_carries_frozen_prd_artifact_to_reviewer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            data = json.loads(plan.read_text(encoding="utf-8"))
            prd_artifact = root / ".agents" / "artifacts" / "PRD_DELIVERY.md"
            prd_artifact.parent.mkdir(parents=True, exist_ok=True)
            prd_artifact.write_text("# PRD_DELIVERY\n", encoding="utf-8")
            result = root / ".agents" / "results" / "prd.json"
            result.parent.mkdir(parents=True, exist_ok=True)
            result.write_text(json.dumps({"schemaVersion": 1, "status": "SUCCEEDED", "prdArtifactPath": str(prd_artifact.resolve()), "outputs": [{"path": "PRD_DELIVERY.md"}]}), encoding="utf-8")
            for task in data["tasks"]:
                if task["taskId"] == "PRD-PRODUCE":
                    task["status"] = "SUCCEEDED"; task["resultPath"] = str(result)
                elif task["taskId"] == "DELIVERY-REVIEW":
                    task["dependencies"] = ["PRD-PRODUCE"]
            plan.write_text(json.dumps(data), encoding="utf-8")
            factory = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "agent_task_factory.py"
            created = self.run_cli(factory, "--run-root", root, "--plan", plan, "--task-id", "DELIVERY-REVIEW", "--requirement", requirement)
            task = json.loads(Path(created["task"]).read_text(encoding="utf-8"))
            self.assertIn(".agents/artifacts/PRD_DELIVERY.md", [item["path"] for item in task["inputs"]])

    def test_factory_rejects_blocked_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            factory = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "agent_task_factory.py"
            self.run_cli(factory, "--run-root", root, "--plan", plan, "--task-id", "PRD-PRODUCE", "--requirement", requirement, expect=1)

    def test_min_loop_executes_prd_only_dag_and_syncs_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            worker = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "deterministic_worker.py"
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", worker)
            self.assertEqual(result["status"], "M1_CONTRACT_COMPLETE")
            data = json.loads(plan.read_text(encoding="utf-8"))
            statuses = {task["taskId"]: task["status"] for task in data["tasks"][:6]}
            expected = ["DECISION-READINESS", "PRD-PRODUCE", "DELIVERY-REVIEW", "QA-RED-TEAM", "TECH-PRD-DIAGNOSIS", "SEMANTIC-CONSISTENCY-REVIEW"]
            for task_id in expected:
                self.assertEqual(statuses[task_id], "SUCCEEDED")
                self.assertTrue(data and next(item for item in data["tasks"] if item["taskId"] == task_id)["runtimeRecordPath"])
                record_path = next(item for item in data["tasks"] if item["taskId"] == task_id)["runtimeRecordPath"]
                record = json.loads(Path(record_path).read_text(encoding="utf-8"))
                self.assertEqual(record["status"], "SUCCEEDED")
                self.assertEqual(record["structuredResultSha256"], __import__("hashlib").sha256(Path(record["structuredResultPath"]).read_bytes()).hexdigest())

    def test_decision_readiness_hold_blocks_before_prd(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            worker = Path(td) / "decision_hold_worker.py"
            worker.write_text("""import json, os
from pathlib import Path
Path(os.environ['AI_NATIVE_RESULT_PATH']).write_text(json.dumps({'schemaVersion':1,'status':'SUCCEEDED','taskId':os.environ['AI_NATIVE_TASK_ID'],'role':os.environ['AI_NATIVE_ROLE'],'outputs':[{'path':'decision-context','kind':'decision-context'}],'readiness':'NOT_READY','decision':'HOLD','blockingConditions':['open product decision'],'requiredDecisions':['confirm scope'],'evidenceRefs':['requirement.md']}))
""", encoding="utf-8")
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", worker, expect=1)
            self.assertEqual(result["status"], "DECISION_BLOCKED")
            self.assertTrue((root / ".agents" / "decisions" / "decision-readiness-block.json").exists())
            data = json.loads(plan.read_text(encoding="utf-8"))
            statuses = {item["taskId"]: item["status"] for item in data["tasks"]}
            self.assertEqual(statuses["DECISION-READINESS"], "FAILED")
            self.assertEqual(statuses["PRD-PRODUCE"], "PENDING")

    def test_worker_failure_stops_in_safe_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            worker = Path(td) / "failing_worker.py"
            worker.write_text("import os\nraise SystemExit(7)\n", encoding="utf-8")
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", worker, expect=1)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["stoppedAt"], "DECISION-READINESS")
            data = json.loads(plan.read_text(encoding="utf-8"))
            decision = next(task for task in data["tasks"] if task["taskId"] == "DECISION-READINESS")
            self.assertEqual(decision["status"], "FAILED")
            next_task = next(task for task in data["tasks"] if task["taskId"] == "PRD-PRODUCE")
            self.assertEqual(next_task["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
