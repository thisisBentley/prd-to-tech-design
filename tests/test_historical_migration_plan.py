import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
SCRIPT = TOOLS / "plan_historical_semantic_migration.py"


def run(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


class HistoricalMigrationPlanTests(unittest.TestCase):
    def fixture(self, root):
        case_root = root / "legacy-case"
        case_root.mkdir()
        prd = case_root / "legacy_PRD.md"
        prd.write_text(
            "# 历史 PRD\n\n"
            "## 需求背景\n历史流程缺少统一记录。\n\n"
            "## 需求目标\n提供可追溯处理。\n\n"
            "## 本期范围\n覆盖提交、审核、异常。\n\n"
            "### 本期不包含\n不覆盖财务打款。\n\n"
            "## 详细需求\n"
            "### FR-001：提交审核\n审批人可以提交审核结果，重复提交必须幂等。\n\n"
            "### FR-002：无权限拒绝\n无权限用户不得提交审核。\n\n"
            "## 业务规则\nBR-001：仅 reviewer 可以提交。\n\n"
            "## 状态\nsubmitted / approved / denied。\n\n"
            "## 异常\n超时和无权限都有明确提示。\n\n"
            "## 权限\nreviewer 可提交。\n\n"
            "## 测试验收\n"
            "| AC | 关联需求 | 验证内容 |\n|---|---|---|\n"
            "| AC-001 | FR-001 | WHEN reviewer 提交；THEN approved；验证幂等。 |\n"
            "| AC-002 | FR-002 | WHEN 无权限用户提交；THEN denied；验证数据未变化。 |\n",
            encoding="utf-8",
        )
        overview = case_root / "legacy_Overview.html"
        overview.write_text(
            '<html><head><meta name="source-prd" content="legacy_PRD.md"></head><body>'
            '<h2>背景与总览</h2><p>历史方案摘要。</p><h2>目标与范围</h2><p>覆盖提交、审核和异常。</p>'
            '<h2>功能与规则</h2><p>FR-001 与 FR-002。</p><h2>方案与流程</h2><p>submitted 到 approved 或 denied。</p>'
            '<h2>验收与保障</h2><p>AC-001 与 AC-002。</p></body></html>',
            encoding="utf-8",
        )
        prototype = case_root / "legacy_Prototype.html"
        prototype.write_text('<html><body><form data-testid="review-form"><button>提交审核</button></form></body></html>', encoding="utf-8")
        spec = {
            "schemaVersion": 1,
            "policyId": "TEST-MIGRATION",
            "samples": [{
                "caseId": "LEGACY-1",
                "sourceRoot": str(case_root),
                "artifactProfile": "PRD_PLUS_PROTOTYPE",
                "artifacts": {"prd": str(prd), "overview": str(overview), "prototype": str(prototype)},
            }],
        }
        spec_path = root / "spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return spec_path, prd, overview, prototype

    def test_generates_candidate_links_without_auto_approval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec, _, _, _ = self.fixture(root)
            out = root / "plans"
            summary = run([SCRIPT, "--spec", spec, "--out-dir", out])
            self.assertEqual(summary["statusCounts"]["PARTIAL"], 1)
            plan = json.loads((out / "LEGACY-1.migration-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["status"], "PARTIAL")
            self.assertEqual(len(plan["frObjects"]), 2)
            self.assertEqual(len(plan["acObjects"]), 2)
            self.assertGreaterEqual(len(plan["candidateLinks"]), 2)
            self.assertTrue(all(link["confidence"] in {"HIGH", "MEDIUM", "LOW"} for link in plan["candidateLinks"]))
            self.assertFalse(plan["overviewMigration"]["sourceHashPresent"])
            self.assertGreater(plan["prototypeBindings"]["legacyCount"], 0)

    def test_ambiguous_ac_is_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec, prd, _, _ = self.fixture(root)
            prd.write_text(prd.read_text(encoding="utf-8").replace("| AC-002 | FR-002 | WHEN 无权限用户提交；THEN denied；验证数据未变化。 |", "| AC-002 |  | 页面整体正确。 |"), encoding="utf-8")
            out = root / "plans"
            run([SCRIPT, "--spec", spec, "--out-dir", out])
            plan = json.loads((out / "LEGACY-1.migration-plan.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["acId"] == "AC-002" for item in plan["unresolved"]))
            self.assertEqual(plan["status"], "PARTIAL")

    def test_missing_prd_blocks_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec, prd, _, _ = self.fixture(root)
            prd.unlink()
            out = root / "plans"
            summary = run([SCRIPT, "--spec", spec, "--out-dir", out])
            self.assertEqual(summary["statusCounts"]["BLOCKED"], 1)
            self.assertFalse((out / "LEGACY-1.migration-plan.json").exists())


if __name__ == "__main__":
    unittest.main()
