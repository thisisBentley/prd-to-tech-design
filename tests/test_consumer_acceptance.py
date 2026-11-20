import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
TOOL = TOOLS / "evaluate_consumer_acceptance.py"
POLICY = ROOT / "config" / "consumer-acceptance" / "policy-v1.json"


def run(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


class ConsumerAcceptanceTests(unittest.TestCase):
    def fixture(self, root):
        prd = root / "PRD_DELIVERY.md"
        prd.write_text(
            "# PRD_DELIVERY\n\n"
            "## 目标 (Goal)\n"
            "让审批人员可以在统一工作台完成费用申请初审，并清楚看到拒绝原因、责任人和下一步操作。\n\n"
            "## 范围 (Scope)\n"
            "本期覆盖费用申请提交、初审、退回补充、权限校验、状态流转、异常恢复和审计留痕；不覆盖最终财务打款。\n\n"
            "## 功能需求 (Functional Requirements)\n"
            "- FR-001: 审批人员可以提交初审结果；无权限时必须拒绝并展示明确原因，重复提交必须保持幂等。\n"
            "- FR-001: 提交成功后记录审批人、时间、审批结论、拒绝原因和关联申请版本，保证后续审计和状态复现。\n\n"
            "## 业务规则 (Business Rules)\n"
            "- BR-001: 只有拥有 expense-reviewer 权限的角色可以提交初审结果。\n"
            "- BR-002: 已退回申请再次提交时，必须校验版本一致，禁止覆盖更新版本。\n\n"
            "## 角色与权限 (Permissions)\n"
            "- submitter: 创建和查看自己的费用申请。\n"
            "- expense-reviewer: 查看待审申请并提交初审结果。\n"
            "- auditor: 只读查看审批记录和操作日志。\n\n"
            "## 状态 (States)\n"
            "- draft: 创建后尚未提交。\n"
            "- submitted: 提交成功，等待初审。\n"
            "- returned: 初审退回，等待申请人补充。\n"
            "- approved: 初审通过，等待财务处理。\n"
            "- error: 提交失败，保留原表单并允许重试。\n\n"
            "## 异常与恢复 (Exceptions and Recovery)\n"
            "- 无权限: 返回 denied 状态并展示原因，不写入审批结果。\n"
            "- 重复提交: 使用幂等键返回首次结果，不生成重复审计记录。\n"
            "- 超时: 展示 timeout 状态，用户可重试且不会产生半提交。\n"
            "- 空数据: 展示 empty 状态并引导用户返回列表。\n\n"
            "## 验收标准 (Acceptance Criteria)\n"
            "### AC-001\n"
            "- WHEN: expense-reviewer 对 submitted 申请提交通过\n"
            "- THEN: 状态变为 approved，并记录审批人、时间、结论和申请版本\n"
            "- 验证: QA 检查状态、审计记录、幂等结果和权限边界\n\n"
            "### AC-002\n"
            "- WHEN: 无权限用户尝试提交初审结果\n"
            "- THEN: 返回 denied，不写入审批结果并展示明确原因\n"
            "- 验证: QA 检查 denied 反馈、数据未变化和审计未新增\n\n"
            "## 非目标 (Non-Goals)\n"
            "- 不覆盖财务打款。\n"
            "- 不覆盖预算调整。\n\n"
            "## 来源与假设\n"
            "业务目标和权限边界来自需求单与已确认产品决策；技术实现方式不在本文定义。\n",
            encoding="utf-8",
        )
        prd_hash = hashlib.sha256(prd.read_bytes()).hexdigest()
        overview = root / "Overview.html"
        overview.write_text(
            "<!doctype html><html><head>"
            f'<meta name="source-prd-sha256" content="{prd_hash}">'
            "</head><body>"
            "<section><h2>方案摘要</h2><p>为审批人员提供可追溯的费用初审流程，明确权限、状态、幂等和拒绝反馈，减少重复提交和审计缺口。</p></section>"
            "<section><h2>背景与现状</h2><p>现有费用申请提交后缺少统一初审记录，申请人无法明确看到退回责任人与下一步操作，审计人员也难以复现审批结论。</p></section>"
            "<section><h2>目标与范围</h2><p>本期覆盖提交、初审、退回、权限、异常恢复和审计留痕，不覆盖财务打款与预算调整，范围边界保持清晰。</p></section>"
            "<section><h2>功能与规则</h2><p>FR-001 对应费用初审提交，BR-001 限制 expense-reviewer 权限，BR-002 约束退回后再次提交的版本一致性，并保证幂等。</p></section>"
            "<section><h2>流程与状态</h2><p>draft 进入 submitted 后由审批人处理，可进入 approved 或 returned；异常时进入 error、timeout、denied 或 empty 状态。</p></section>"
            "<section><h2>验收与风险</h2><p>AC-001 和 AC-002 覆盖成功、无权限、幂等和审计证据。风险包括权限配置错误、超时重试和旧版本覆盖。</p></section>"
            "</body></html>",
            encoding="utf-8",
        )
        prototype = root / "Prototype.html"
        prototype.write_text(
            '<!doctype html><html><body>'
            '<form data-ai-id="expense-review-form" data-ai-fr="FR-001" data-ai-ac="AC-001" data-ai-state="submitted,approved" data-ai-permission="expense-reviewer">'
            '<label>审批意见</label><button>提交初审</button></form>'
            '<div data-ai-id="denied-message" data-ai-fr="FR-001" data-ai-ac="AC-002" data-ai-state="denied,error" data-ai-permission="submitter">无权限</div>'
            '<div data-ai-id="empty-state" data-ai-state="empty">暂无待审申请</div>'
            '<div data-ai-id="timeout-state" data-ai-state="timeout">请求超时，请重试</div>'
            '</body></html>',
            encoding="utf-8",
        )
        manifest = root / "prototype-manifest.json"
        manifest.write_text(json.dumps({
            "schemaVersion": 1,
            "workflowId": "WF-CONSUMER-1",
            "prototypeRevision": "r1",
            "elements": [
                {"uiElementId": "expense-review-form", "frIds": ["FR-001"], "acIds": ["AC-001"], "states": ["submitted", "approved"], "permissions": ["expense-reviewer"]},
                {"uiElementId": "denied-message", "frIds": ["FR-001"], "acIds": ["AC-002"], "states": ["denied", "error"], "permissions": ["submitter"]},
                {"uiElementId": "empty-state", "frIds": ["FR-001"], "acIds": ["AC-002"], "states": ["empty"], "permissions": []},
                {"uiElementId": "timeout-state", "frIds": ["FR-001"], "acIds": ["AC-002"], "states": ["timeout"], "permissions": []},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        runtime = root / "runtime.json"
        runtime.write_text(json.dumps({
            "schemaVersion": 2,
            "status": "PASS",
            "executionMode": "real-browser",
            "runtimeEvidenceLevel": "REAL_BROWSER",
            "prototypeHash": hashlib.sha256(prototype.read_bytes()).hexdigest(),
            "consoleErrors": [],
            "pageErrors": [],
            "requestFailures": [],
            "checks": [],
        }), encoding="utf-8")
        jira = root / "Jira_Description.md"
        jira.write_text(
            f"<!-- source-prd-sha256: {prd_hash} -->\n"
            "## 1. 背景\n费用申请提交后缺少统一初审记录。\n"
            "## 2. 现状\n申请人无法明确看到退回责任人与下一步操作。\n"
            "## 3. 目标\n提供可追溯的费用初审流程。\n"
            "## 4. 功能点\nFR-001 提交费用初审结果。\n",
            encoding="utf-8",
        )
        review = root / "prd-review.json"
        review.write_text(json.dumps({"schemaVersion": 1, "result": "PASS", "findings": [], "blockingFindings": 0}), encoding="utf-8")
        contract = root / "decision-contract.json"
        contract.write_text(json.dumps({
            "schemaVersion": 1,
            "contractId": "DC-1",
            "workflowId": "WF-CONSUMER-1",
            "targetRevision": "r1",
            "prdSha256": prd_hash,
            "status": "PASS",
            "readiness": "READY",
            "traceability": {"decisionToObjects": {}, "objectToDecisions": {}, "uncoveredP0P1ObjectIds": []},
            "metrics": {"decisions": 1, "closed": 1, "openBlocking": 0, "mappedObjects": 2, "traceableObjects": 2},
            "findings": [],
        }, ensure_ascii=False), encoding="utf-8")
        readiness = root / "decision-readiness.json"
        readiness.write_text(json.dumps({"schemaVersion": 1, "status": "PASS", "errors": []}), encoding="utf-8")
        code = root / "code-baseline.json"
        code.write_text(json.dumps({"module": "expense-review", "endpoints": ["/expense/review"]}), encoding="utf-8")
        source_lock = root / "source-lock.json"
        source_lock.write_text(json.dumps({
            "schemaVersion": 1,
            "sources": [
                {"role": "prd", "sourceType": "PRD", "path": str(prd), "sha256": prd_hash},
                {"role": "code", "sourceType": "CODE", "path": str(code), "sha256": hashlib.sha256(code.read_bytes()).hexdigest()},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        request = {
            "schemaVersion": 1,
            "workflowId": "WF-CONSUMER-1",
            "caseId": "CASE-CONSUMER-1",
            "targetRevision": "r1",
            "artifactProfile": "PRD_PLUS_PROTOTYPE",
            "caseClassification": "REAL",
            "producer": {"role": "delivery-producer", "contextId": "producer-1"},
            "productManager": {"role": "product-manager-consumer", "contextId": "pm-1"},
            "architect": {"role": "architect-consumer", "contextId": "arch-1"},
            "artifacts": {
                "prd": str(prd),
                "overview": str(overview),
                "jira": str(jira),
                "prototype": str(prototype),
                "prototypeManifest": str(manifest),
                "runtimeEvidence": str(runtime),
                "prdReviewResult": str(review),
                "decisionContract": str(contract),
                "decisionReadiness": str(readiness),
                "sourceLock": str(source_lock),
            },
            "evidenceRefs": ["jira://CASE-CONSUMER-1"],
        }
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        return request_path, request, {"prd": prd, "overview": overview, "prototype": prototype, "contract": contract, "source_lock": source_lock}

    def evaluate(self, root, request_path, expect=0):
        out = root / "consumer-report.json"
        result = run([TOOL, "--request", request_path, "--policy", POLICY, "--out", out], expect=expect)
        return result, json.loads(out.read_text(encoding="utf-8"))

    def test_rich_real_case_passes_and_becomes_m7_exit_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, _, _ = self.fixture(root)
            result, report = self.evaluate(root, request_path)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(report["m7ExitEvidenceEligible"])
            self.assertTrue(report["humanConsumerReviewRequired"])
            self.assertEqual(report["productManager"]["status"], "PASS")
            self.assertEqual(report["architect"]["status"], "PASS")

    def test_fixture_pass_is_not_m7_exit_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, request, _ = self.fixture(root)
            request["caseClassification"] = "FIXTURE"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            _, report = self.evaluate(root, request_path)
            self.assertEqual(report["status"], "PASS")
            self.assertFalse(report["m7ExitEvidenceEligible"])

    def test_thin_overview_needs_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, _, paths = self.fixture(root)
            prd_hash = hashlib.sha256(paths["prd"].read_bytes()).hexdigest()
            paths["overview"].write_text(f'<html><head><meta name="source-prd-sha256" content="{prd_hash}"></head><body><h2>方案摘要</h2><p>FR-001 AC-001</p><h2>背景与现状</h2><p>FR-001</p><h2>目标与范围</h2><p>FR-001</p><h2>功能与规则</h2><p>FR-001</p><h2>流程与状态</h2><p>FR-001</p><h2>验收与风险</h2><p>AC-001</p></body></html>', encoding="utf-8")
            result, report = self.evaluate(root, request_path, expect=1)
            self.assertEqual(report["status"], "NEEDS_REVIEW")
            self.assertTrue(any(item["code"] == "PM_OVERVIEW_THIN" for item in report["findings"]))

    def test_shared_context_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, request, _ = self.fixture(root)
            request["architect"]["contextId"] = request["producer"]["contextId"]
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            _, report = self.evaluate(root, request_path, expect=1)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertTrue(any(item["code"] == "CONSUMER_CONTEXT_NOT_INDEPENDENT" for item in report["findings"]))

    def test_decision_contract_not_ready_blocks_architect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, _, paths = self.fixture(root)
            contract = json.loads(paths["contract"].read_text())
            contract["status"] = "BLOCKED"
            contract["readiness"] = "BLOCKED"
            paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
            _, report = self.evaluate(root, request_path, expect=1)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["architect"]["status"], "BLOCKED")

    def test_source_hash_drift_blocks_architect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, _, paths = self.fixture(root)
            data = json.loads(paths["source_lock"].read_text())
            data["sources"][1]["sha256"] = "0" * 64
            paths["source_lock"].write_text(json.dumps(data), encoding="utf-8")
            _, report = self.evaluate(root, request_path, expect=1)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertTrue(any(item["code"] == "ARCH_SOURCE_LOCK_NOT_CONSUMABLE" for item in report["findings"]))

    def test_final_gate_requires_two_distinct_real_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, request, _ = self.fixture(root)
            reports = []
            for case_id in ("CASE-CONSUMER-A", "CASE-CONSUMER-B"):
                data = dict(request)
                data["caseId"] = case_id
                path = root / f"{case_id}.request.json"
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                report_path = root / f"{case_id}.report.json"
                run([TOOL, "--request", path, "--policy", POLICY, "--out", report_path])
                reports.append(report_path)
            gate_root = root / "gate-run"
            gate_root.mkdir()
            cmd = [
                sys.executable, str(TOOLS / "final_gatekeeper.py"),
                "--run-root", str(gate_root), "--requirement-name", "Demo",
                "--skip-delivery", "--skip-tech",
                "--trust-kernel-run", str(ROOT / "examples" / "trust-kernel" / "trust-kernel-run.json"),
                "--submission-contract", str(ROOT / "examples" / "submission-contract" / "contract.json"),
                "--submission-manifest", str(ROOT / "examples" / "submission-contract" / "manifest.json"),
            ]
            for report in reports:
                cmd.extend(["--consumer-acceptance-report", str(report)])
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            consumer = next(item for item in payload["checks"] if item["checkId"] == "FINAL.CONSUMER.ACCEPTANCE")
            self.assertEqual(consumer["status"], "passed")
            self.assertEqual(len(consumer["observed"]["distinctCaseIds"]), 2)

    def test_static_runtime_is_not_product_manager_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, request, _ = self.fixture(root)
            runtime_path = Path(request["artifacts"]["runtimeEvidence"])
            runtime = json.loads(runtime_path.read_text())
            runtime["executionMode"] = "static-contract"
            runtime["runtimeEvidenceLevel"] = "STATIC_CONTRACT"
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            _, report = self.evaluate(root, request_path, expect=1)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertTrue(any(item["code"] == "PM_PROTOTYPE_RUNTIME_NOT_AUTHORITATIVE" for item in report["findings"]))


if __name__ == "__main__":
    unittest.main()
