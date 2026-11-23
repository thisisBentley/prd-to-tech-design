import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
PLANNER = TOOLS / "plan_historical_semantic_migration.py"
QUEUE_BUILDER = TOOLS / "build_historical_migration_review_queue.py"
ADJUDICATOR = TOOLS / "apply_historical_migration_decisions.py"


def invoke(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return (json.loads(proc.stdout) if proc.stdout.strip() else None), proc


class HistoricalMigrationReviewQueueTests(unittest.TestCase):
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
            "policyId": "TEST-MIGRATION-QUEUE",
            "samples": [{
                "caseId": "LEGACY-1",
                "sourceRoot": str(case_root),
                "artifactProfile": "PRD_PLUS_PROTOTYPE",
                "artifacts": {"prd": str(prd), "overview": str(overview), "prototype": str(prototype)},
            }],
        }
        spec_path = root / "spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        plans = root / "plans"
        invoke([PLANNER, "--spec", spec_path, "--out-dir", plans])
        queue_path = root / "review-queue.json"
        summary, _ = invoke([QUEUE_BUILDER, "--plans-dir", plans, "--out", queue_path])
        return {
            "root": root,
            "prd": prd,
            "queue_path": queue_path,
            "queue": json.loads(queue_path.read_text(encoding="utf-8")),
            "summary": summary,
        }

    def decision_record(self, fixture, entries):
        queue_path = fixture["queue_path"]
        queue = fixture["queue"]
        return {
            "schemaVersion": 1,
            "queueId": queue["queueId"],
            "queueSha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
            "reviewer": {
                "reviewerId": "product-owner-1",
                "role": "PRODUCT_OWNER",
                "independentFromAgent": True,
                "attestation": "I reviewed the cited source evidence and approve the recorded decisions.",
            },
            "decisions": entries,
            "createdAt": "2026-11-23T00:00:00+00:00",
        }

    def write_decisions(self, fixture, decision):
        path = fixture["root"] / "decisions.json"
        path.write_text(json.dumps(decision, ensure_ascii=False), encoding="utf-8")
        return path

    def test_queue_contains_all_acs_and_never_auto_approves(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self.fixture(Path(td))
            queue = fixture["queue"]
            ac_items = [item for item in queue["items"] if item["kind"] == "FR_AC_ASSOCIATION"]
            self.assertEqual(len(ac_items), 2)
            self.assertEqual(queue["summary"]["candidateBackedAcCount"], 2)
            self.assertEqual(queue["summary"]["unresolvedAcCount"], 0)
            self.assertTrue(all(item["status"] == "AWAITING_DECISION" for item in queue["items"]))
            self.assertFalse(queue["m7ExitEvidenceEligible"])
            self.assertFalse(queue["trainingEligible"])
            self.assertGreaterEqual(queue["summary"]["taskItemCount"], 2)

    def test_complete_adjudication_creates_approved_mappings_only(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self.fixture(Path(td))
            queue = fixture["queue"]
            entries = []
            for item in queue["items"]:
                if item["kind"] == "FR_AC_ASSOCIATION":
                    entries.append({
                        "itemId": item["itemId"],
                        "decision": "APPROVE_MAPPING",
                        "reason": "The source AC row explicitly names the selected FR.",
                        "evidenceRefs": [str(fixture["prd"])],
                        "approvedFrIds": [item["candidateLinks"][0]["frId"]],
                    })
                else:
                    entries.append({
                        "itemId": item["itemId"],
                        "decision": "MARK_COMPLETED",
                        "reason": "The migration action was completed with the cited evidence.",
                        "evidenceRefs": [str(fixture["prd"])],
                    })
            decision_path = self.write_decisions(fixture, self.decision_record(fixture, entries))
            out = fixture["root"] / "adjudication.json"
            summary, _ = invoke([ADJUDICATOR, "--queue", fixture["queue_path"], "--decisions", decision_path, "--out", out])
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "COMPLETE")
            self.assertTrue(result["migrationReadyForPackaging"])
            self.assertEqual(len(result["approvedMappings"]), 2)
            self.assertEqual(result["counts"]["pending"], 0)
            self.assertFalse(result["m7ExitEvidenceEligible"])
            self.assertFalse(result["trainingEligible"])

    def test_partial_decisions_leave_remaining_items_pending(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self.fixture(Path(td))
            item = next(item for item in fixture["queue"]["items"] if item["kind"] == "FR_AC_ASSOCIATION")
            decision = self.decision_record(fixture, [{
                "itemId": item["itemId"],
                "decision": "APPROVE_MAPPING",
                "reason": "The source AC row explicitly names the selected FR.",
                "evidenceRefs": [str(fixture["prd"])],
                "approvedFrIds": [item["candidateLinks"][0]["frId"]],
            }])
            decision_path = self.write_decisions(fixture, decision)
            out = fixture["root"] / "adjudication.json"
            summary, _ = invoke([ADJUDICATOR, "--queue", fixture["queue_path"], "--decisions", decision_path, "--out", out])
            self.assertEqual(summary["status"], "PARTIAL")
            self.assertFalse(summary["migrationReadyForPackaging"])
            self.assertGreater(summary["counts"]["pending"], 0)

    def test_unknown_fr_and_duplicate_decisions_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self.fixture(Path(td))
            item = next(item for item in fixture["queue"]["items"] if item["kind"] == "FR_AC_ASSOCIATION")
            bad = {
                "itemId": item["itemId"],
                "decision": "APPROVE_MAPPING",
                "reason": "The source evidence supports this mapping.",
                "evidenceRefs": [str(fixture["prd"])],
                "approvedFrIds": ["FR-999"],
            }
            decision_path = self.write_decisions(fixture, self.decision_record(fixture, [bad]))
            _, proc = invoke([ADJUDICATOR, "--queue", fixture["queue_path"], "--decisions", decision_path, "--out", fixture["root"] / "bad.json"], expect=2)
            self.assertIn("not in the source plan", proc.stderr)

            valid = {**bad, "approvedFrIds": [item["candidateLinks"][0]["frId"]]}
            duplicate_path = self.write_decisions(fixture, self.decision_record(fixture, [valid, valid]))
            _, proc = invoke([ADJUDICATOR, "--queue", fixture["queue_path"], "--decisions", duplicate_path, "--out", fixture["root"] / "duplicate.json"], expect=2)
            self.assertIn("duplicate decision", proc.stderr)

    def test_queue_hash_or_authority_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = self.fixture(Path(td))
            decision = self.decision_record(fixture, [])
            decision["queueSha256"] = "0" * 64
            decision_path = self.write_decisions(fixture, decision)
            _, proc = invoke([ADJUDICATOR, "--queue", fixture["queue_path"], "--decisions", decision_path, "--out", fixture["root"] / "bad-hash.json"], expect=2)
            self.assertIn("queueSha256", proc.stderr)

            decision = self.decision_record(fixture, [])
            decision["reviewer"]["role"] = "AGENT"
            decision_path = self.write_decisions(fixture, decision)
            _, proc = invoke([ADJUDICATOR, "--queue", fixture["queue_path"], "--decisions", decision_path, "--out", fixture["root"] / "bad-role.json"], expect=2)
            self.assertIn("invalid historical migration decision record", proc.stderr)


if __name__ == "__main__":
    unittest.main()
