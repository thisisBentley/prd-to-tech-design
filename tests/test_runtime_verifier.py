import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "verify_prototype_runtime.py"


class RuntimeVerifierTests(unittest.TestCase):
    def fixtures(self, root):
        prototype = root / "Prototype.html"
        prototype.write_text("<!doctype html><html><body><button>Continue</button></body></html>", encoding="utf-8")
        return prototype

    def test_static_fallback_is_explicitly_not_real_browser(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prototype = self.fixtures(root); out = root / "runtime.json"
            proc = subprocess.run([sys.executable, str(TOOL), "--prototype", str(prototype), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["executionMode"], "static-contract")
            self.assertEqual(result["runtimeEvidenceLevel"], "STATIC_CONTRACT")
            self.assertEqual(result["consoleErrors"], [])

    def test_require_real_browser_blocks_static_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prototype = self.fixtures(root); out = root / "runtime.json"
            proc = subprocess.run([sys.executable, str(TOOL), "--prototype", str(prototype), "--out", str(out), "--require-real-browser"], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "INSUFFICIENT")
            self.assertEqual(result["runtimeEvidenceLevel"], "STATIC_CONTRACT")

    def test_browser_adapter_evidence_is_captured(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prototype = self.fixtures(root); out = root / "runtime.json"
            runner = root / "runner.py"
            runner.write_text("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({\"status\":\"PASS\",\"executionMode\":\"real-browser\",\"browserVersion\":\"test-1\",\"consoleErrors\":[],\"pageErrors\":[],\"requestFailures\":[],\"checks\":[{\"checkId\":\"BROWSER.LOAD\",\"status\":\"passed\",\"observed\":\"ok\",\"expected\":\"ok\",\"evidenceRefs\":[\"prototype\"]}]}))\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--prototype", str(prototype), "--out", str(out), "--require-real-browser", "--browser-runner", sys.executable, str(runner)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["runtimeEvidenceLevel"], "REAL_BROWSER")
            self.assertEqual(result["browserVersion"], "test-1")

    def test_browser_errors_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prototype = self.fixtures(root); out = root / "runtime.json"
            runner = root / "runner.py"
            runner.write_text("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({\"status\":\"PASS\",\"executionMode\":\"real-browser\",\"consoleErrors\":[{\"message\":\"boom\"}],\"pageErrors\":[],\"requestFailures\":[],\"checks\":[]}))\n", encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--prototype", str(prototype), "--out", str(out), "--browser-runner", sys.executable, str(runner)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "NEEDS_FIX")


if __name__ == "__main__":
    unittest.main()
