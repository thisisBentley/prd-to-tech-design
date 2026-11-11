import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools") / "build_generation_contract.py"


class GenerationContractTests(unittest.TestCase):
    def run_tool(self, *args, expect=0):
        process = subprocess.run([sys.executable, str(TOOL), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def test_detects_conditional_ui_and_permission_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            requirement = root / "requirement.md"
            requirement.write_text(
                "# 客户导出\n\n## 目标\n运营可以在客户页面导出客户列表。\n\n"
                "## 范围\n仅支持有客户查看权限的用户。\n\n"
                "## 业务规则\n筛选后导出全部数据，空数据显示暂无数据，失败提示重试。\n\n"
                "## 验收\nAC-001 WHEN 导出 THEN 返回当前结果。\n",
                encoding="utf-8",
            )
            out = root / "generation-contract.json"
            result = self.run_tool(
                "--requirement", requirement, "--workflow-id", "WF-1", "--requirement-id", "REQ-1",
                "--artifact-profile", "PRD_ONLY", "--out", out,
            )
            self.assertEqual(result["status"], "READY_WITH_ACTIONS")
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("UI_INTERACTION", data["requirementTypes"])
            self.assertTrue(any(item["checkId"] == "GC.TYPE.UI" for item in data["checks"]))
            self.assertGreater(data["metrics"]["needsProduct"], 0)

    def test_missing_requirement_source_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing = root / "missing.md"
            result = self.run_tool(
                "--requirement", missing, "--workflow-id", "WF-1", "--requirement-id", "REQ-1",
                "--out", root / "out.json", expect=1,
            )
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
