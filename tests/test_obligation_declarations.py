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
COLLECT = SCRIPTS / "collect_obligation_declarations.py"
VALIDATE = SCRIPTS / "validate_obligation_declarations.py"


class ObligationDeclarationTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def setup_docs(self, root: Path):
        lock = root / "policy-lock.json"
        self.run_tool(LOCK, "--artifact-profile", "PRD_PLUS_PROTOTYPE", "--requirement-types", "CRUD,UI_INTERACTION", "--prototype-status", "TRIGGERED", "--ui-ownership", "LOCAL", "--out", lock)
        obligations = root / "obligations.json"
        self.run_tool(OBLIGATIONS, "--policy-lock", lock, "--workflow-id", "WF-1", "--out", obligations)
        return lock, obligations, json.loads(obligations.read_text())

    def declarations_for(self, obligations: dict):
        return {"schemaVersion": 1, "workflowId": obligations["workflowId"], "targetRevision": obligations["targetRevision"], "policyLockSha256": obligations["policyLockSha256"], "generatedAt": "2026-11-11T00:00:00Z", "declarations": [
            {"obligationId": item["obligationId"], "ruleId": item["ruleId"], "producerRole": item["ownerRole"], "producerTaskId": "TASK-1", "status": "DECLARED", "artifact": item["artifact"], "location": f"{item['artifact']}#declared", "evidenceRefs": [f"evidence://{item['ruleId']}"]}
            for item in obligations["obligations"] if item.get("declarationRequired")
        ]}

    def test_valid_declarations_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, obligations_path, obligations = self.setup_docs(root)
            decl_path = root / "declarations.json"
            decl_path.write_text(json.dumps(self.declarations_for(obligations)), encoding="utf-8")
            collected = root / "collected.json"
            result = self.run_tool(COLLECT, "--obligations", obligations_path, "--input", decl_path, "--out", collected)
            self.assertEqual(result["status"], "COMPLETE")
            validation = root / "validation.json"
            result = self.run_tool(VALIDATE, "--obligations", obligations_path, "--declarations", collected, "--out", validation)
            self.assertEqual(result["status"], "PASS")
            self.assertGreater(result["required"], 0)

    def test_missing_required_declaration_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, obligations_path, obligations = self.setup_docs(root)
            dec = self.declarations_for(obligations)
            dec["declarations"] = dec["declarations"][:-1]
            decl_path = root / "declarations.json"
            decl_path.write_text(json.dumps(dec), encoding="utf-8")
            collected = root / "collected.json"
            self.run_tool(COLLECT, "--obligations", obligations_path, "--input", decl_path, "--out", collected)
            validation = root / "validation.json"
            self.run_tool(VALIDATE, "--obligations", obligations_path, "--declarations", collected, "--out", validation, expect=1)
            result = json.loads(validation.read_text())
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("missing declaration" in error for error in result["errors"]))

    def test_not_applicable_does_not_close_required_obligation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, obligations_path, obligations = self.setup_docs(root)
            dec = self.declarations_for(obligations)
            dec["declarations"][0]["status"] = "NOT_APPLICABLE"
            dec["declarations"][0]["reason"] = "fixture"
            decl_path = root / "declarations.json"
            decl_path.write_text(json.dumps(dec), encoding="utf-8")
            collected = root / "collected.json"
            self.run_tool(COLLECT, "--obligations", obligations_path, "--input", decl_path, "--out", collected)
            validation = root / "validation.json"
            self.run_tool(VALIDATE, "--obligations", obligations_path, "--declarations", collected, "--out", validation, expect=1)
            result = json.loads(validation.read_text())
            self.assertTrue(any("must be DECLARED" in error for error in result["errors"]))

    def test_policy_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, obligations_path, obligations = self.setup_docs(root)
            dec = self.declarations_for(obligations)
            dec["policyLockSha256"] = "f" * 64
            decl_path = root / "declarations.json"
            decl_path.write_text(json.dumps(dec), encoding="utf-8")
            validation = root / "validation.json"
            self.run_tool(VALIDATE, "--obligations", obligations_path, "--declarations", decl_path, "--out", validation, expect=1)
            result = json.loads(validation.read_text())
            self.assertIn("declaration policyLockSha256 does not match generation obligations", result["errors"])


if __name__ == "__main__":
    unittest.main()
