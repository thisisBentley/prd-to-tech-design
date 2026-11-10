import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "preflight_prototype.py"


class PrototypePreflightTests(unittest.TestCase):
    def test_missing_visible_label_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd = root / "prd.md"; proto = root / "proto.html"; out = root / "out.json"
            prd.write_text("current_prd_version: v1.2\n本页面提供可见可点的查看日志入口。", encoding="utf-8")
            proto.write_text('<meta name="source-prd-version" content="v1.2"><button @click="drillDownToLogs()">统计</button>', encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--prd", prd, "--prototype", proto, "--out", out], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "NEEDS_FIX")
            self.assertTrue(any(c["checkId"] == "VISIBLE.查看日志" and c["status"] == "failed" for c in result["checks"]))


    def test_reused_unified_permission_feedback_is_not_a_prototype_label_requirement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd = root / "prd.md"; proto = root / "proto.html"; runtime = root / "runtime.json"; out = root / "out.json"
            prd.write_text("current_prd_version: v1.2\n无权限用户进入既有统一无权限反馈，不新增权限页面。", encoding="utf-8")
            proto.write_text('<meta name="source-prd-version" content="v1.2"><div>业务页面</div>', encoding="utf-8")
            runtime.write_text(json.dumps({"status": "PASS", "consoleErrors": [], "pageErrors": [], "requestFailures": []}), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--prd", prd, "--prototype", proto, "--runtime-result", runtime, "--out", out], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(out.read_text())
            self.assertTrue(any(c["checkId"] == "VISIBLE.无权限" and c["status"] == "not_applicable" for c in result["checks"]))

    def test_not_triggered_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd = root / "prd.md"; out = root / "out.json"
            prd.write_text("PRD", encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--prd", prd, "--out", out], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(json.loads(out.read_text())["status"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
