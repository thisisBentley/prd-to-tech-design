import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
LOCK = SCRIPTS / "build_policy_lock.py"
OBLIGATIONS = SCRIPTS / "build_generation_obligations.py"
FACTORY = SCRIPTS / "agent_task_factory.py"


class GenerationObligationTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def lock(self, root: Path, profile="PRD_PLUS_PROTOTYPE", types="CRUD,UI_INTERACTION"):
        out = root / "policy-lock.json"
        self.run_tool(LOCK, "--artifact-profile", profile, "--requirement-types", types, "--prototype-status", "TRIGGERED", "--ui-ownership", "LOCAL", "--out", out)
        return out

    def test_obligations_are_owned_by_producers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = self.lock(root)
            out = root / "obligations.json"
            result = self.run_tool(OBLIGATIONS, "--policy-lock", lock, "--workflow-id", "WF-1", "--out", out)
            self.assertEqual(result["status"], "PASS")
            data = json.loads(out.read_text())
            owners = {item["ownerRole"] for item in data["obligations"]}
            self.assertIn("prd-producer", owners)
            self.assertIn("prototype-producer", owners)
            self.assertTrue(any(item["ruleId"] == "G1.MUST.ROLES_PERMISSIONS" and item["ownerRole"] == "prd-producer" for item in data["obligations"]))
            self.assertTrue(any(item["ruleId"] == "U1.MANIFEST_BINDING" and item["ownerRole"] == "prototype-producer" for item in data["obligations"]))
            self.assertEqual(data["policyLockSha256"], __import__("hashlib").sha256(lock.read_bytes()).hexdigest())

    def test_prd_only_excludes_prototype_obligations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = self.lock(root, profile="PRD_ONLY", types="CRUD")
            out = root / "obligations.json"
            self.run_tool(OBLIGATIONS, "--policy-lock", lock, "--workflow-id", "WF-1", "--out", out)
            data = json.loads(out.read_text())
            self.assertFalse(any(item["ruleId"].startswith(("U1.", "U2.")) for item in data["obligations"]))

    def test_agent_task_freezes_policy_and_obligation_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = root / "requirement.md"
            root.mkdir(parents=True)
            requirement.write_text("# Demo\n\nFR-001\nAC-001\n", encoding="utf-8")
            (root / ".agents" / "policy").mkdir(parents=True)
            (root / ".agents" / "context").mkdir(parents=True)
            lock = self.lock(root / ".agents" / "policy")
            obligations = root / ".agents" / "policy" / "generation-obligations.json"
            self.run_tool(OBLIGATIONS, "--policy-lock", lock, "--workflow-id", "WF-1", "--out", obligations)
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "schemaVersion": 1, "planId": "P1", "workflowId": "WF-1", "requirementId": "DEMO", "artifactProfile": "PRD_PLUS_PROTOTYPE", "iteration": "r1",
                "tasks": [
                    {"taskId": "DECISION-READINESS", "role": "decision-readiness-agent", "kind": "decision", "dependencies": [], "readScope": [], "writeScope": [], "expectedOutputs": ["decision"], "status": "SUCCEEDED", "resultPath": ""},
                    {"taskId": "PRD-PRODUCE", "role": "prd-producer", "kind": "producer", "dependencies": ["DECISION-READINESS"], "readScope": [], "writeScope": [], "expectedOutputs": ["PRD"], "status": "PENDING"},
                ], "createdAt": "2026-11-11T00:00:00Z",
            }), encoding="utf-8")
            self.run_tool(FACTORY, "--run-root", root, "--plan", plan, "--task-id", "PRD-PRODUCE", "--requirement", requirement, "--runtime", "noop")
            task = json.loads((root / ".agents" / "tasks" / "PRD-PRODUCE.task.json").read_text())
            paths = {item["path"] for item in task["inputs"]}
            self.assertIn(".agents/policy/policy-lock.json", paths)
            self.assertIn(".agents/policy/generation-obligations.json", paths)
            self.assertTrue(any("Generation obligations" in item for item in task["constraints"]))


if __name__ == "__main__":
    unittest.main()
