import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
BUILD = SCRIPTS / "build_delivery_semantic_model.py"
REVIEW = SCRIPTS / "review_delivery_semantics.py"

PRD = """# Demo PRD

## 1. 需求背景
### 1.3 本期范围
本期包含客户导出。

### 1.4 角色与访问权限
| 角色 | 可见 | 操作 |
|---|---|---|
| 运营 | 可见 | 导出 |

## 2. 需求目标
### 2.2 目标列表
| 目标 ID | 目标 | 关联功能 |
|---|---|---|
| G-001 | 运营可导出客户 | FR-001 |

## 3. 详细需求
### 3.1 功能需求总览
| FR ID | 功能名称 |
|---|---|
| FR-001 | 客户导出 |

### 3.2 FR-001：客户导出
#### 3.2.1 需求说明
运营可以导出客户。
#### 3.2.2 前置与触发
有客户查看权限时点击导出。
#### 3.2.3 产品逻辑
按筛选结果导出全部数据。
#### 3.2.4 业务规则
超过一万条提示缩小范围。
#### 3.2.5 交互
点击导出按钮。
#### 3.2.6 用户可见文案
成功提示导出任务已提交。
#### 3.2.7 状态
处理中、成功、失败。
#### 3.2.8 数据
客户名称、等级。
#### 3.2.9 异常
失败提示重试。

## 4. 测试验收
### 4.1 AC-001 导出成功
- 关联功能：FR-001
- 前置条件：有权限且存在数据
- WHEN：点击导出
- THEN：生成当前筛选结果文件
- 验收方式：页面操作 + 文件核对
"""


class SemanticDecompositionTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def test_builds_units_edges_and_global_contracts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd = root / "PRD_DELIVERY.md"
            prd.write_text(PRD, encoding="utf-8")
            model_path = root / "semantic-model.json"
            self.run_tool(BUILD, "--prd", prd, "--workflow-id", "WF-1", "--artifact-profile", "PRD_ONLY", "--out", model_path)
            model = json.loads(model_path.read_text(encoding="utf-8"))
            self.assertEqual(model["metrics"]["featureSlices"], 1)
            self.assertEqual(model["metrics"]["acceptanceCriteria"], 1)
            self.assertEqual(model["metrics"]["journeys"], 1)
            self.assertTrue(any(item["contractId"] == "GC-PERMISSIONS" for item in model["globalContracts"]))
            self.assertTrue(any(edge["relation"] == "VERIFIED_BY" for edge in model["edges"]))
            feature = next(item for item in model["units"] if item["unitId"] == "FR-001")
            self.assertIn("GC-PERMISSIONS", feature["dependencies"])

    def test_review_detects_ui_coverage_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd = root / "PRD_DELIVERY.md"
            prd.write_text(PRD, encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "schemaVersion": 1, "manifestId": "M-1", "workflowId": "WF-1", "prototypeRevision": "r1",
                "prototypePath": "prototype.html", "prototypeHash": "a" * 64,
                "elements": [{"uiElementId": "UI-OTHER", "frIds": ["FR-001"], "acIds": ["AC-999"], "visibleLabel": "其他", "states": ["default"]}],
                "createdAt": "2026-11-11T00:00:00Z",
            }), encoding="utf-8")
            model_path = root / "semantic-model.json"
            review_path = root / "review.json"
            self.run_tool(BUILD, "--prd", prd, "--workflow-id", "WF-1", "--artifact-profile", "PRD_PLUS_PROTOTYPE", "--manifest", manifest, "--out", model_path)
            self.run_tool(REVIEW, "--model", model_path, "--out", review_path, expect=1)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertEqual(review["status"], "NEEDS_FIX")
            failed = {item["checkId"] for item in review["checks"] if item["status"] == "failed"}
            self.assertIn("EDGE.UI_BINDINGS", failed)
            self.assertIn("GLOBAL.AC_UI_COVERAGE", failed)


if __name__ == "__main__":
    unittest.main()
