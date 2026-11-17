import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
TOOL = SCRIPTS / "resolve_unit_applicability.py"


class UnitApplicabilityTests(unittest.TestCase):
    def run_tool(self, *args, expect=0):
        process = subprocess.run([sys.executable, str(TOOL), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_maps_rules_to_fr_ui_permissions_and_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd = root / "PRD.md"
            prd.write_text("# PRD\n\n## Permissions\n- owner may view\n\n- FR-001: user configures fields\n- AC-001: fields are saved\n\n- FR-002: system switches type\n- AC-002: state is retained\n", encoding="utf-8")
            manifest = root / "prototype-manifest.json"
            manifest.write_text(json.dumps({"elements": [{"uiElementId": "UI-001", "frIds": ["FR-001"], "acIds": ["AC-001"], "states": ["default"]}]}), encoding="utf-8")
            lock = {"policyPackId": "P1", "applicableRules": {
                "R0": ["R0.ARTIFACT_SET"], "G1": ["G1.MUST.ROLES_PERMISSIONS", "G1.MUST.STATES_EXCEPTIONS"],
                "O1": ["O1.SIX_TABS"], "U1": ["U1.MANIFEST_BINDING"], "U2": [], "QA": ["QA.AC_COVERAGE"], "Q1": ["Q1.HASH_STABILITY"]
            }}
            lock_path = root / "lock.json"; lock_path.write_text(json.dumps(lock), encoding="utf-8")
            out = root / "out.json"
            result = self.run_tool("--policy-lock", lock_path, "--prd", prd, "--manifest", manifest, "--workflow-id", "WF", "--revision", "r1", "--out", out)
            self.assertEqual(result["status"], "PASS")
            report = json.loads(out.read_text())
            by_rule = {item["ruleId"]: item for item in report["rules"]}
            self.assertEqual(by_rule["R0.ARTIFACT_SET"]["targetUnitIds"], ["PACKAGE"])
            self.assertEqual(by_rule["G1.MUST.ROLES_PERMISSIONS"]["targetUnitIds"], ["PERMISSIONS"])
            self.assertIn("FR-002", by_rule["G1.MUST.STATES_EXCEPTIONS"]["targetUnitIds"])
            self.assertEqual(by_rule["U1.MANIFEST_BINDING"]["targetUnitIds"], ["UI-001"])
            self.assertEqual(report["metrics"]["uiUnits"], 1)


if __name__ == "__main__":
    unittest.main()
