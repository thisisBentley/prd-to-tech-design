import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
PIPELINE = ROOT / SCRIPTS / "delivery_pipeline.py"


class DeliveryPipelineTests(unittest.TestCase):
    def run_pipeline(self, root, requirement, profile, prototype_status, ui_ownership, expect=0):
        process = subprocess.run([
            sys.executable, str(PIPELINE), "--run-root", str(root), "--requirement", str(requirement),
            "--workflow-id", "WF-PIPELINE", "--requirement-name", "Pipeline Demo", "--requirement-id", "PIPE-1",
            "--artifact-profile", profile, "--prototype-status", prototype_status, "--ui-ownership", ui_ownership,
        ], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def requirement(self, root):
        path = root / "requirement.md"
        path.write_text("""# Scene Intent Feature

- FR-001: user can view result
- AC-001: result is visible

## Permissions
- task-owner ALLOWED view result
- viewer DENIED edit result

## States
- default: precondition defined by PRD and reachable from home
""", encoding="utf-8")
        return path

    def assert_package(self, root, result, profile):
        self.assertEqual(result["status"], "PACKAGE_READY")
        kinds = {item["kind"] for item in result["artifacts"]}
        self.assertTrue({"PRD", "OVERVIEW", "JIRA_DESCRIPTION"} <= kinds)
        if profile != "PRD_ONLY":
            self.assertIn("PROTOTYPE", kinds)
        self.assertTrue((root / "01-delivery" / "PRD_DELIVERY.md").exists())
        self.assertTrue((root / "01-delivery" / "Jira_Description.md").exists())
        quality = json.loads((root / ".agents" / "quality" / "delivery-quality-exit.json").read_text())
        self.assertEqual(quality["status"], "PASS")
        handoff = json.loads(Path(result["handoff"]).read_text())
        self.assertEqual(handoff["workflowId"], "WF-PIPELINE")
        complete = json.loads(Path(result["completeGate"]).read_text())
        failed = {item["checkId"] for item in complete["checks"] if item["status"] == "failed"}
        self.assertIn("COMPLETE.P0_5_BENCHMARK", failed)
        self.assertIn("COMPLETE.REPLAY", failed)
        self.assertNotIn("COMPLETE.EVIDENCE_FILES", failed)
        self.assertNotIn("COMPLETE.SEMANTIC_REVIEW", failed)

    def test_prd_only_pipeline_builds_all_non_ui_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            result = self.run_pipeline(root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE")
            self.assert_package(root, result, "PRD_ONLY")

    def test_pair_pipeline_builds_prototype_pair_semantic_review_and_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            result = self.run_pipeline(root, requirement, "PRD_PLUS_PROTOTYPE", "TRIGGERED", "LOCAL")
            self.assert_package(root, result, "PRD_PLUS_PROTOTYPE")
            pair = json.loads((root / ".agents" / "m2" / "artifact-pair.json").read_text())
            self.assertEqual(pair["pairStatus"], "SYNCED")
            semantic = json.loads(Path(result["semanticReview"]).read_text())
            self.assertEqual(semantic["verdict"], "ACCEPTED")
            self.assertTrue(any(check["checkId"] == "SEMANTIC.COVERAGE" for check in semantic["checks"]))


if __name__ == "__main__":
    unittest.main()
