import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("cross", ROOT / "tools" / "check_cross_artifact_contracts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CrossArtifactTests(unittest.TestCase):
    def test_reproduces_zy779_five_gap_classes(self):
        mod = load()
        fixture = ROOT / "tests" / "fixtures" / "zy779-regression"
        result = mod.check((fixture / "prd.md").read_text(), (fixture / "prototype.html").read_text())
        self.assertEqual(result["result"], "NEEDS_FIX")
        self.assertEqual(result["blockingFindings"], 5)
        self.assertEqual({f["ruleId"] for f in result["findings"]}, set(mod.RULES))

    def test_clean_contract_passes(self):
        mod = load()
        prd = """
        Role matrix: 运营管理员 can view summary; 技术管理员 can view technical details; denied users see no details.
        Export contract: CSV, 1000 max records, empty/failure/permission results defined. AC-009 verifies export.
        Overdue-stage enum: PD, M1, M2; unknown is excluded.
        Exception fields: code, detail.field.
        [TIMEOUT] appears as a distinct timeout event. AC-004 verifies it.
        """
        proto = "运营管理员 技术管理员 code detail.field timeout-event CSV"
        result = mod.check(prd, proto)
        self.assertEqual(result["result"], "PASS", result)

    def test_cli_emits_machine_result(self):
        fixture = ROOT / "tests" / "fixtures" / "zy779-regression"
        proc = subprocess.run([
            sys.executable, str(ROOT / "tools" / "check_cross_artifact_contracts.py"),
            "--prd", str(fixture / "prd.md"), "--prototype", str(fixture / "prototype.html"), "--json",
        ], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertEqual(data["result"], "NEEDS_FIX")


if __name__ == "__main__":
    unittest.main()
