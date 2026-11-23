import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILD = TOOLS / "build_delivery_operating_procedure.py"
VALIDATE = TOOLS / "validate_delivery_operating_procedure.py"
SOURCE_PACK = ROOT / "config" / "source-packs" / "current-v1.json"
TOOL_POLICY = ROOT / "config" / "trust-kernel" / "specialist-tool-routes-v1.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class DeliveryOperatingProcedureTests(unittest.TestCase):
    def fixture(self, root):
        requirement = root / "requirement.md"
        requirement.write_text("# Customer Export\n\n- FR-001: export visible rows\n- AC-001: WHEN export THEN current rows are returned\n", encoding="utf-8")
        generation = {
            "schemaVersion": 1,
            "workflowId": "WF-DOP",
            "requirementId": "REQ-DOP",
            "artifactProfile": "PRD_ONLY",
            "generatedAt": "2026-11-23T00:00:00+00:00",
            "requirementTypes": ["CRUD", "UI_INTERACTION"],
            "status": "READY",
            "checks": [],
            "metrics": {"checks": 1, "passed": 1, "warnings": 0, "needsRole": 0, "needsProduct": 0, "blocked": 0},
        }
        policy = {
            "schemaVersion": 1,
            "policyPackId": "PACK",
            "policyPackVersion": "1",
            "ruleSetVersion": "1",
            "policyPackSha256": "a" * 64,
            "generatedAt": "2026-11-23T00:00:00+00:00",
            "scope": {"artifactProfile": "PRD_ONLY", "requirementTypes": ["CRUD"], "prototypeStatus": "NOT_TRIGGERED", "uiOwnership": "NONE"},
            "applicableRules": {gate: [f"{gate}.RULE"] for gate in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]},
            "excludedRules": [],
        }
        plan = {
            "schemaVersion": 1,
            "planId": "PLAN-1",
            "workflowId": "WF-DOP",
            "requirementId": "REQ-DOP",
            "artifactProfile": "PRD_ONLY",
            "iteration": "r1",
            "tasks": [{
                "taskId": "PRD-PRODUCE", "role": "prd-producer", "kind": "producer",
                "dependencies": [], "readScope": ["01-delivery/**"], "writeScope": ["01-delivery/**"],
                "expectedOutputs": ["PRD"], "required": True, "status": "PENDING",
            }],
            "createdAt": "2026-11-23T00:00:00+00:00",
        }
        budget = {"schemaVersion": 1, "budgetName": "TEST", "maxTotalSeconds": 100, "maxJobSeconds": 10, "maxContextFiles": 20, "maxTranscriptBytes": 1000, "maxRepairRounds": 2}
        repair = {"schemaVersion": 1, "policyId": "REPAIR", "mode": "SHADOW_ONLY", "maxRounds": 2, "requireIndependentVerifier": True, "requireRebuild": True, "regressionStopsImmediately": True, "requireAllChangeSetsForReady": True}
        paths = {}
        for name, data in (("generation", generation), ("policy", policy), ("plan", plan), ("budget", budget), ("repair", repair)):
            path = root / f"{name}.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            paths[name] = path
        obligations = {
            "schemaVersion": 1,
            "workflowId": "WF-DOP",
            "targetRevision": "r1",
            "policyLockPath": str(paths["policy"]),
            "policyLockSha256": digest(paths["policy"]),
            "generatedAt": "2026-11-23T00:00:00+00:00",
            "obligations": [],
            "metrics": {"total": 3, "open": 3},
        }
        obligations_path = root / "obligations.json"
        obligations_path.write_text(json.dumps(obligations), encoding="utf-8")
        paths["obligations"] = obligations_path
        paths["requirement"] = requirement
        return paths

    def build_args(self, paths, out, **overrides):
        values = {
            "workflow_id": "WF-DOP",
            "requirement_id": "REQ-DOP",
            "artifact_profile": "PRD_ONLY",
            "generation": paths["generation"],
            "policy": paths["policy"],
            "obligations": paths["obligations"],
            "plan": paths["plan"],
            "tool_policy": TOOL_POLICY,
            "budget": paths["budget"],
            "repair": paths["repair"],
            "source_pack": SOURCE_PACK,
            "requirement": paths["requirement"],
        }
        values.update(overrides)
        return [
            BUILD, "--workflow-id", values["workflow_id"], "--requirement-id", values["requirement_id"],
            "--artifact-profile", values["artifact_profile"], "--revision", "r1",
            "--requirement", values["requirement"], "--generation-contract", values["generation"],
            "--policy-lock", values["policy"], "--obligations", values["obligations"],
            "--plan", values["plan"], "--tool-policy", values["tool_policy"],
            "--budget", values["budget"], "--repair-policy", values["repair"],
            "--source-pack", values["source_pack"], "--out", out,
        ]

    def test_builds_unified_operating_procedure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            out = root / "dop.json"
            result = run(self.build_args(paths, out))
            self.assertEqual(result["status"], "READY")
            procedure = json.loads(out.read_text())
            self.assertEqual(procedure["goalContract"]["objectiveSource"], "REQUIREMENT_TITLE")
            self.assertEqual(procedure["metrics"]["subgoals"], 1)
            self.assertEqual(procedure["metrics"]["toolRoutes"], 3)
            self.assertEqual(procedure["guardrails"]["obligationsOpen"], 3)
            self.assertGreaterEqual(procedure["metrics"]["guardrailRules"], 7)
            self.assertIn("MAX_REPAIR_ROUNDS_REACHED", procedure["stopPolicy"]["conditions"])
            self.assertTrue(procedure["revisionPolicy"]["staleEvidenceForbidden"])
            validated = run([VALIDATE, "--procedure", out, "--verify-source-hashes"])
            self.assertEqual(validated["status"], "PASS")

    def test_workflow_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            plan = json.loads(paths["plan"].read_text())
            plan["workflowId"] = "WF-OTHER"
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = run(self.build_args(paths, root / "dop.json"), expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("delivery plan workflowId does not match", result["error"])

    def test_policy_hash_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            obligations = json.loads(paths["obligations"].read_text())
            obligations["policyLockSha256"] = "b" * 64
            paths["obligations"].write_text(json.dumps(obligations), encoding="utf-8")
            result = run(self.build_args(paths, root / "dop.json"), expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("policyLockSha256 does not match", result["error"])

    def test_repair_budget_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.fixture(root)
            budget = json.loads(paths["budget"].read_text())
            budget["maxRepairRounds"] = 1
            paths["budget"].write_text(json.dumps(budget), encoding="utf-8")
            result = run(self.build_args(paths, root / "dop.json"), expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("does not match repair policy", result["error"])


if __name__ == "__main__":
    unittest.main()
