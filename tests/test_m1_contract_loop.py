import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
ORCH = ROOT / SCRIPTS / "orchestrate.py"
LOOP = ROOT / SCRIPTS / "delivery_loop.py"
WORKER = ROOT / SCRIPTS / "deterministic_worker.py"


class M1ContractLoopTests(unittest.TestCase):
    def run_cli(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def prepare(self, root, text):
        requirement = root / "requirement.md"
        requirement.write_text(text, encoding="utf-8")
        plan = root / "plan.json"
        self.run_cli(ORCH, "init", "--run-root", root, "--workflow-id", "WF-M1", "--requirement-name", "M1 Demo", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
        self.run_cli(ORCH, "build-delivery-plan", "--run-root", root, "--out", plan)
        return plan, requirement

    def validate_contract(self, path):
        process = subprocess.run([sys.executable, str(ROOT / SCRIPTS / "validate_agent_contracts.py"), str(path)], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_intake_auto_builds_work_plan_and_reaches_m1(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            requirement = root / "requirement.md"
            requirement.write_text("# Requirement\n\nAuto-build the Delivery Work Plan.\n", encoding="utf-8")
            self.run_cli(ORCH, "init", "--run-root", root, "--workflow-id", "WF-M1-AUTO", "--requirement-name", "M1 Auto", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
            result = self.run_cli(LOOP, "--run-root", root, "--requirement", requirement, "--worker", WORKER)
            self.assertEqual(result["status"], "M1_CONTRACT_COMPLETE")
            auto_plan = root / ".agents" / "delivery-work-plan.json"
            self.assertTrue(auto_plan.exists())
            plan_data = json.loads(auto_plan.read_text(encoding="utf-8"))
            self.assertEqual(plan_data["artifactProfile"], "PRD_ONLY")
            self.assertTrue(any(item["taskId"] == "PRD-PRODUCE" for item in plan_data["tasks"]))

    def test_prd_artifact_is_generated_frozen_and_used_as_review_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root, "# Requirement\n\nBuild expense submission.\n")
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", WORKER)
            self.assertEqual(result["status"], "M1_CONTRACT_COMPLETE")
            artifact = root / ".agents" / "artifacts" / "PRD_DELIVERY.md"
            self.assertTrue(artifact.exists())
            text = artifact.read_text(encoding="utf-8")
            self.assertIn("# PRD_DELIVERY", text)
            self.assertIn("expense submission", text.lower())
            produced_result = json.loads((root / ".agents" / "results" / "PRD-PRODUCE.result.json").read_text(encoding="utf-8"))
            self.assertEqual(produced_result["prdArtifactPath"], str(artifact.resolve()))
            review = json.loads((root / ".agents" / "reviews" / "DELIVERY-REVIEW.review.json").read_text(encoding="utf-8"))
            self.assertIn(str(artifact.resolve()), review["evidenceRefs"])
            data = json.loads(plan.read_text(encoding="utf-8"))
            produced_task = next(item for item in data["tasks"] if item["taskId"] == "PRD-PRODUCE")
            self.assertTrue(Path(produced_task["resultPath"]).exists())
            self.assertIn("PRD_DELIVERY", produced_result["outputs"][0]["path"])

    def test_clean_path_reaches_m1_contract_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root, "# Requirement\n\nClean PRD_ONLY.\n")
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", WORKER)
            self.assertEqual(result["status"], "M1_CONTRACT_COMPLETE")
            data = json.loads(plan.read_text(encoding="utf-8"))
            statuses = {item["taskId"]: item["status"] for item in data["tasks"]}
            for task_id in ["FINAL-PACKAGE-REVIEW", "DELIVERY-GATEKEEPER", "DELIVERY-HANDOFF"]:
                self.assertEqual(statuses[task_id], "SUCCEEDED")
            self.assertFalse(any(task_id.startswith("RECHECK-") for task_id in statuses))
            handoff_path = root / ".agents" / "handoffs" / "delivery-ready.handoff.json"
            self.assertTrue(handoff_path.exists())
            self.validate_contract(handoff_path)
            for name in ["FINAL-PACKAGE-REVIEW.review.json", "DELIVERY-GATEKEEPER.review.json"]:
                self.validate_contract(root / ".agents" / "reviews" / name)
            gatekeeper = json.loads((root / ".agents" / "reviews" / "DELIVERY-GATEKEEPER.review.json").read_text(encoding="utf-8"))
            self.assertEqual(gatekeeper["verdict"], "ACCEPTED")
            self.assertEqual(gatekeeper["blockingCount"], 0)

    def test_blocking_path_repairs_rechecks_and_reaches_m1(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root, "# Requirement\n\nBLOCKING\n")
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", WORKER)
            self.assertEqual(result["status"], "M1_CONTRACT_COMPLETE")
            data = json.loads(plan.read_text(encoding="utf-8"))
            statuses = {item["taskId"]: item["status"] for item in data["tasks"]}
            self.assertEqual(next(item for item in data["tasks"] if item["taskId"].startswith("PRD-REPAIR-"))["status"], "SUCCEEDED")
            for task_id in ["RECHECK-DELIVERY-REVIEW", "RECHECK-QA-RED-TEAM", "RECHECK-TECH-PRD-DIAGNOSIS", "RECHECK-SEMANTIC-CONSISTENCY", "FINAL-PACKAGE-REVIEW", "DELIVERY-GATEKEEPER", "DELIVERY-HANDOFF"]:
                self.assertEqual(statuses[task_id], "SUCCEEDED")
            for task_id in ["RECHECK-DELIVERY-REVIEW", "RECHECK-QA-RED-TEAM", "RECHECK-TECH-PRD-DIAGNOSIS", "RECHECK-SEMANTIC-CONSISTENCY"]:
                self.validate_contract(root / ".agents" / "reviews" / f"{task_id}.review.json")
            self.validate_contract(root / ".agents" / "handoffs" / "delivery-ready.handoff.json")
            batch = next(Path(item["resultPath"]) for item in data["tasks"] if item["taskId"] == "FINDING-CONSOLIDATE")
            self.assertTrue(json.loads(batch.read_text(encoding="utf-8"))["blockingCount"] > 0)


if __name__ == "__main__":
    unittest.main()
