import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "tools" / "orchestrate.py"
VALIDATOR = ROOT / "tools" / "validate_artifact_profile.py"


class ArtifactProfileTests(unittest.TestCase):
    def run_cli(self, *args, expect=0):
        proc = subprocess.run([sys.executable, *map(str, args)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_init_records_artifact_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "demo"
            result = self.run_cli(
                ORCH, "init", "--run-root", root, "--workflow-id", "WF-1",
                "--requirement-name", "Demo", "--artifact-profile", "EXTERNAL_UI_BOUNDARY",
                "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "EXTERNAL",
            )
            self.assertEqual(result["status"], "READY")
            state = json.loads((root / ".agents" / "orchestration.json").read_text())
            self.assertEqual(state["artifactProfile"], "EXTERNAL_UI_BOUNDARY")
            self.assertEqual(state["prototypeStatus"], "NOT_TRIGGERED")
            self.assertEqual(state["uiOwnership"], "EXTERNAL")

    def test_external_ui_boundary_profile_passes(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "profile.json"
            profile.write_text(json.dumps({
                "schemaVersion": 1,
                "artifactProfile": "EXTERNAL_UI_BOUNDARY",
                "prototypeStatus": "NOT_TRIGGERED",
                "uiOwnership": "EXTERNAL",
                "prototypeReason": "customer owns the UI",
                "uiBoundaryContractRequired": True,
                "localUiAcceptance": "NOT_APPLICABLE",
            }), encoding="utf-8")
            result = self.run_cli(VALIDATOR, profile)
            self.assertEqual(result["status"], "PASS")

    def test_triggered_prototype_requires_visible_interaction_and_clean_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "profile.json"
            contract = Path(td) / "prototype-contract.json"
            profile.write_text(json.dumps({
                "schemaVersion": 1,
                "artifactProfile": "PRD_PLUS_PROTOTYPE",
                "prototypeStatus": "TRIGGERED",
                "uiOwnership": "LOCAL",
            }), encoding="utf-8")
            contract.write_text(json.dumps({
                "schemaVersion": 1,
                "requirementId": "DEMO-1",
                "artifactProfile": "PRD_PLUS_PROTOTYPE",
                "prototypeStatus": "TRIGGERED",
                "status": "PASS",
                "consoleErrors": 0,
                "checks": [{
                    "checkId": "VISIBLE.LOG",
                    "status": "passed",
                    "evidenceRefs": ["prototype.html#composition"],
                    "observed": "查看日志 is visible and clickable",
                    "expected": "visible label and preserved context",
                    "visibleInteraction": {
                        "ruleId": "FR-008",
                        "visibleLabel": "查看日志",
                        "triggerArea": "composition",
                        "targetView": "sessionLog",
                        "preserveContext": ["dateRange", "status"],
                        "expectedEvidence": {
                            "domText": "查看日志",
                            "clickable": True,
                            "targetView": "sessionLog",
                            "contextPreserved": True,
                            "consoleErrors": 0,
                        },
                    },
                }],
            }), encoding="utf-8")
            result = self.run_cli(VALIDATOR, profile, "--prototype-contract", contract)
            self.assertEqual(result["status"], "PASS")

    def test_not_triggered_contract_cannot_pass(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "profile.json"
            contract = Path(td) / "prototype-contract.json"
            profile.write_text(json.dumps({
                "schemaVersion": 1,
                "artifactProfile": "EXTERNAL_UI_BOUNDARY",
                "prototypeStatus": "NOT_TRIGGERED",
                "uiOwnership": "EXTERNAL",
            }), encoding="utf-8")
            contract.write_text(json.dumps({
                "schemaVersion": 1,
                "requirementId": "DEMO-1",
                "artifactProfile": "EXTERNAL_UI_BOUNDARY",
                "prototypeStatus": "NOT_TRIGGERED",
                "status": "PASS",
                "consoleErrors": 0,
                "checks": [],
            }), encoding="utf-8")
            result = self.run_cli(VALIDATOR, profile, "--prototype-contract", contract, expect=1)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("NOT_TRIGGERED" in e for e in result["errors"]))

    def test_runtime_pass_rejects_console_errors(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "profile.json"
            runtime = Path(td) / "runtime.json"
            profile.write_text(json.dumps({"schemaVersion": 1, "artifactProfile": "PRD_PLUS_PROTOTYPE", "prototypeStatus": "TRIGGERED", "uiOwnership": "LOCAL"}), encoding="utf-8")
            runtime.write_text(json.dumps({"status": "PASS", "runtimeVerified": True, "consoleDiagnostics": ["TypeError"]}), encoding="utf-8")
            result = self.run_cli(VALIDATOR, profile, "--runtime-result", runtime, expect=1)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("console" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
