import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
SCRIPT = TOOLS / "run_historical_consumer_replay.py"


def run(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


class HistoricalConsumerReplayTests(unittest.TestCase):
    def fixture(self, root, *, with_binding=True):
        run_root = root / "history-case"
        run_root.mkdir()
        prd = run_root / "需求_PRD_DELIVERY.md"
        prd.write_text(
            "# 需求 PRD-DELIVERY\n\n"
            "## 1. 需求背景\n现有流程缺少统一记录，运营无法追溯。\n\n"
            "## 2. 需求目标\n提供可追溯的统一处理流程。\n\n"
            "## 3. 范围\n覆盖提交、审批和异常恢复。\n\n"
            "### 本期不包含\n不覆盖财务打款。\n\n"
            "## 4. 详细需求\n### FR-001：提交审批\n审批人可以提交初审结果，重复提交必须幂等。\n\n"
            "## 5. 业务规则\nBR-001：无权限用户不得提交。\n\n"
            "## 6. 状态\nsubmitted / approved / denied / error。\n\n"
            "## 7. 异常\n超时、无权限和空数据均有明确反馈。\n\n"
            "## 8. 权限\n只有 expense-reviewer 可以提交。\n\n"
            "## 9. 测试验收\n"
            "| AC | 关联需求 | 验证内容 |\n|---|---|---|\n"
            "| AC-001 | FR-001 | WHEN 审批人提交；THEN 状态变为 approved；验证审计记录和幂等结果。 |\n"
            "| AC-002 | FR-001 | WHEN 无权限用户提交；THEN 返回 denied；验证数据未变化。 |\n",
            encoding="utf-8",
        )
        overview = run_root / "需求_Overview.html"
        overview.write_text(
            '<!doctype html><html><head><meta name="source-prd" content="需求_PRD_DELIVERY.md"><meta name="source-prd-version" content="v1.1"></head><body>'
            '<h2>背景与总览</h2><h3>方案摘要</h3><p>为审批人员提供可追溯的统一处理流程，覆盖权限、幂等与异常反馈。</p>'
            '<h2>目标与范围</h2><h3>本期目标</h3><p>覆盖提交、审批、状态流转、异常恢复和审计证据，不覆盖财务打款。</p>'
            '<h2>功能与规则</h2><p>FR-001 对应提交审批，BR-001 限制审批权限，并保证幂等。</p>'
            '<h2>方案与流程</h2><p>submitted 进入 approved 或 denied，异常进入 error 并允许重试。</p>'
            '<h2>验收与保障</h2><p>AC-001 与 AC-002 覆盖成功、无权限、幂等和审计结果。</p>'
            '</body></html>',
            encoding="utf-8",
        )
        prototype = run_root / "需求_Prototype.html"
        prototype.write_text(
            "<html><body>"
            + ('<form data-testid="review-form"><button>提交审批</button></form>' if with_binding else '<form><button>提交审批</button></form>')
            + '<div data-unauthorized-state="true">无权限</div><div data-empty-table="true">空态</div><div data-loading-state="true">加载中</div>'
            + '</body></html>',
            encoding="utf-8",
        )
        runtime = run_root / "browser-runtime.json"
        runtime.write_text(json.dumps({"checks": {"load": {"loaded": True, "errors": []}}}), encoding="utf-8")
        gates = run_root / "gates"
        gates.mkdir()
        (gates / "G1.json").write_text(json.dumps({"result": "PASS"}), encoding="utf-8")
        (gates / "QA.json").write_text(json.dumps({"result": "PASS"}), encoding="utf-8")
        spec = {
            "schemaVersion": 1,
            "policyId": "TEST-HISTORY",
            "samples": [{
                "caseId": "HISTORY-1",
                "sourceRoot": str(run_root),
                "artifactProfile": "PRD_PLUS_PROTOTYPE",
                "artifacts": {
                    "prd": str(prd),
                    "overview": str(overview),
                    "prototype": str(prototype),
                    "runtime": str(runtime),
                    "gatesDir": str(gates),
                },
            }],
        }
        spec_path = root / "spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return spec_path, prd, overview, prototype

    def test_legacy_package_replays_as_partial_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec, prd, _, _ = self.fixture(root)
            out = root / "out"
            summary = run([SCRIPT, "--spec", spec, "--out-dir", out])
            self.assertEqual(summary["caseCount"], 1)
            self.assertEqual(summary["statusCounts"]["REPLAY_PARTIAL"], 1)
            report = json.loads((out / "HISTORY-1.historical-replay.json").read_text(encoding="utf-8"))
            self.assertEqual(report["caseClassification"], "HISTORICAL_REPLAY")
            self.assertFalse(report["m7ExitEvidenceEligible"])
            self.assertEqual(report["versionCompatibility"], "PARTIAL")
            self.assertTrue(any(item["code"] == "OVERVIEW_HASH_NOT_BOUND" for item in report["gaps"]))

    def test_missing_legacy_binding_blocks_content_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec, _, _, _ = self.fixture(root, with_binding=False)
            out = root / "out"
            summary = run([SCRIPT, "--spec", spec, "--out-dir", out])
            self.assertEqual(summary["statusCounts"]["REPLAY_BLOCKED"], 1)
            report = json.loads((out / "HISTORY-1.historical-replay.json").read_text(encoding="utf-8"))
            self.assertEqual(report["contentReadiness"], "BLOCKED")
            self.assertTrue(any(item["code"] == "PROTOTYPE_BINDING_MISSING" for item in report["gaps"]))

    def test_nested_overview_headings_do_not_truncate_tab_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec, _, overview, _ = self.fixture(root)
            out = root / "out"
            run([SCRIPT, "--spec", spec, "--out-dir", out])
            report = json.loads((out / "HISTORY-1.historical-replay.json").read_text(encoding="utf-8"))
            check = next(item for item in report["checks"] if item["checkId"] == "HISTORY.OVERVIEW.LEGACY_TABS")
            self.assertEqual(check["status"], "passed", check)


if __name__ == "__main__":
    unittest.main()
