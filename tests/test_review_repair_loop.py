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


class ReviewRepairLoopTests(unittest.TestCase):
    def run_cli(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        if process.stdout.strip():
            return json.loads(process.stdout)
        return {}

    def prepare(self, root, requirement_text="# Requirement\n\nClean PRD_ONLY requirement.\n"):
        requirement = root / "requirement.md"
        requirement.write_text(requirement_text, encoding="utf-8")
        plan = root / "plan.json"
        self.run_cli(ORCH, "init", "--run-root", root, "--workflow-id", "WF-REVIEW", "--requirement-name", "Review Demo", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
        self.run_cli(ORCH, "build-delivery-plan", "--run-root", root, "--out", plan)
        return plan, requirement

    def test_clean_requirement_reviews_and_consolidates_without_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root)
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", WORKER)
            self.assertEqual(result["status"], "M1_CONTRACT_COMPLETE")
            data = json.loads(plan.read_text(encoding="utf-8"))
            finding = next(task for task in data["tasks"] if task["taskId"] == "FINDING-CONSOLIDATE")
            self.assertEqual(finding["status"], "SUCCEEDED")
            batch_path = Path(finding["resultPath"])
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            self.assertEqual(batch["status"], "NO_FINDINGS")
            review_dir = root / ".agents" / "reviews"
            reviews = sorted(review_dir.glob("*.review.json"))
            self.assertEqual(len(reviews), 6)
            for review_path in reviews:
                process = subprocess.run([sys.executable, str(ROOT / SCRIPTS / "validate_agent_contracts.py"), str(review_path)], text=True, capture_output=True)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_blocking_requirement_creates_repair_task_and_repair_completes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; root.mkdir()
            plan, requirement = self.prepare(root, "# Requirement\n\nBLOCKING\n")
            result = self.run_cli(LOOP, "--run-root", root, "--plan", plan, "--requirement", requirement, "--worker", WORKER)
            self.assertEqual(result["status"], "M1_CONTRACT_COMPLETE")
            data = json.loads(plan.read_text(encoding="utf-8"))
            repairs = [task for task in data["tasks"] if task["taskId"].startswith("PRD-REPAIR-")]
            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0]["status"], "SUCCEEDED")
            self.assertTrue(repairs[0].get("runtimeRecordPath"))
            statuses = {item["taskId"]: item["status"] for item in data["tasks"]}
            for task_id in ["RECHECK-DELIVERY-REVIEW", "RECHECK-QA-RED-TEAM", "RECHECK-TECH-PRD-DIAGNOSIS", "RECHECK-SEMANTIC-CONSISTENCY", "FINAL-PACKAGE-REVIEW", "DELIVERY-GATEKEEPER", "DELIVERY-HANDOFF"]:
                self.assertEqual(statuses[task_id], "SUCCEEDED")
            self.assertEqual(repairs[0]["role"], "prd-repair-agent")
            self.assertEqual(repairs[0]["repairClass"], "SEMANTIC")
            self.assertEqual(repairs[0]["rootCauseId"], "requirement-blocking-marker")
            batch_path = next(Path(task["resultPath"]) for task in data["tasks"] if task["taskId"] == "FINDING-CONSOLIDATE")
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            self.assertEqual(batch["status"], "READY_FOR_REPAIR")
            self.assertEqual(batch["blockingCount"], 3)
            # Main loop can now pick the generated repair task; current stop point is explicit.
            repair_sync = result["completed"][-1]["taskSync"]
            self.assertEqual(repair_sync["taskStatus"], "SUCCEEDED")
            self.assertEqual(repair_sync["runtimeStatus"], "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
