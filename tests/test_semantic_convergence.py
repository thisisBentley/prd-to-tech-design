import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
LEDGER = TOOLS / "build_semantic_ledger.py"
REGISTRY = TOOLS / "build_invariant_registry.py"
CONVERGENCE = TOOLS / "evaluate_convergence.py"
REVIEW = TOOLS / "apply_invariant_review.py"
AUDIT = TOOLS / "audit_invariant_candidates.py"
HISTORY_AUDIT = TOOLS / "audit_convergence_history.py"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class SemanticConvergenceTests(unittest.TestCase):
    def fixture(self, root):
        prd = root / "PRD.md"
        prd.write_text("# Demo\n\nFR-001\nAC-001\n", encoding="utf-8")
        model = root / "semantic-model.json"
        model.write_text(json.dumps({
            "schemaVersion": 1,
            "workflowId": "WF-1",
            "targetRevision": "r1",
            "artifactProfile": "PRD_ONLY",
            "source": {"prdPath": str(prd), "prdSha256": "a" * 64},
            "globalContracts": [{
                "contractId": "GC-PERMISSIONS",
                "kind": "PERMISSION",
                "title": "权限",
                "statement": "无编辑权限时不展示编辑入口。",
                "sourceRef": f"{prd}#权限",
                "authority": "PRD",
                "status": "ACTIVE"
            }],
            "units": [{
                "unitId": "FR-001",
                "kind": "FEATURE_SLICE",
                "title": "保存规则",
                "statement": "保存业务规则。",
                "sourceRef": f"{prd}#FR-001",
                "authority": "PRD",
                "frIds": ["FR-001"],
                "acIds": ["AC-001"],
                "dependencies": ["GC-PERMISSIONS"],
                "sections": {"业务规则": "条件命中但没有有效参数时不得入队。", "交互与状态": "无权限时不展示入口。"},
                "fields": {},
                "content": "保存业务规则。"
            }, {
                "unitId": "AC-001",
                "kind": "ACCEPTANCE_CRITERION",
                "title": "无参数保持缓冲",
                "statement": "无有效参数时保持缓冲。",
                "sourceRef": f"{prd}#AC-001",
                "authority": "PRD",
                "frIds": ["FR-001"],
                "acIds": ["AC-001"],
                "dependencies": ["FR-001"],
                "sections": {},
                "fields": {"WHEN": "没有有效参数", "THEN": "保持缓冲且不占用坐席", "验收方式": "运行态核对"},
                "content": "无有效参数时保持缓冲。"
            }],
            "edges": [{"edgeId": "E1", "fromUnitId": "AC-001", "toUnitId": "FR-001", "relation": "VERIFIES", "status": "ACTIVE", "evidenceRefs": [str(prd)]}],
            "findings": [],
            "metrics": {"globalContracts": 1, "featureSlices": 1, "acceptanceCriteria": 1, "interactionContracts": 0, "journeys": 0, "edges": 1},
            "generatedAt": "2026-11-19T00:00:00+08:00"
        }), encoding="utf-8")
        ledger = root / "ledger.json"
        registry = root / "registry.json"
        run([LEDGER, "--semantic-model", model, "--out", ledger])
        run([REGISTRY, "--ledger", ledger, "--out", registry])
        return ledger, registry

    def lock_registry(self, path, revision="r1"):
        data = json.loads(path.read_text())
        data["targetRevision"] = revision
        for item in data["invariants"]:
            item["status"] = "LOCKED"
            item["lockedBy"] = "human-reviewer"
            item["lockedAt"] = "2026-11-19T00:00:00+08:00"
            item["reviewResultRef"] = "review.json"
        data["metrics"] = {"invariants": len(data["invariants"]), "candidate": 0, "active": 0, "locked": len(data["invariants"]), "deprecated": 0}
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def write_snapshot(self, path, revision, findings, verified=None, violated=None):
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "snapshotId": f"S-{revision}",
            "workflowId": "WF-1",
            "revision": revision,
            "findings": findings,
            "verifiedInvariantIds": verified or [],
            "violatedInvariantIds": violated or [],
            "createdAt": "2026-11-19T00:00:00+08:00"
        }), encoding="utf-8")
        return path

    def policy(self, root):
        path = root / "policy.json"
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "policyId": "CONV-1",
            "severityWeights": {"BLOCKING": 10, "NON_BLOCKING": 3, "INFO": 1},
            "requireWeightedDecrease": True,
            "requireNoNewBlocking": True,
            "requireNoReopenedRootCause": True,
            "requireNoInvariantViolation": True,
            "requireNoSemanticDrift": True,
            "requireNoScopeDrift": True,
            "requireLockedInvariantCoverage": True,
            "createdAt": "2026-11-19T00:00:00+08:00"
        }), encoding="utf-8")
        return path

    def finding(self, finding_id, root_cause, status="OPEN", severity="BLOCKING", code="SPEC_CONTRADICTION", affected=None, invariant_ids=None, reopened=False):
        return {
            "findingId": finding_id,
            "rootCauseId": root_cause,
            "severity": severity,
            "status": status,
            "code": code,
            "affectedObjectIds": affected or ["FR-001"],
            "invariantIds": invariant_ids or [],
            "evidenceRefs": ["review.json"],
            "reopened": reopened
        }

    def test_ledger_and_candidate_registry_use_explicit_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger_path, registry_path = self.fixture(root)
            ledger = json.loads(ledger_path.read_text())
            registry = json.loads(registry_path.read_text())
            self.assertTrue(any(item["objectType"] == "BUSINESS_RULE" for item in ledger["objects"]))
            self.assertTrue(any(item["objectType"] == "INTERACTION_RULE" for item in ledger["objects"]))
            self.assertGreaterEqual(registry["metrics"]["candidate"], 3)
            self.assertEqual(registry["metrics"]["locked"], 0)

    def test_convergence_rejects_new_blocking_and_missing_locked_invariant(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = self.lock_registry(registry_path, "r2")
            policy = self.policy(root)
            baseline = self.write_snapshot(root / "baseline.json", "r1", [self.finding("F-1", "RC-1")], verified=[item["invariantId"] for item in registry["invariants"]])
            current = self.write_snapshot(root / "current.json", "r2", [self.finding("F-2", "RC-2")], verified=[])
            result = run([CONVERGENCE, "--baseline", baseline, "--current", current, "--policy", policy, "--invariant-registry", registry_path, "--out", root / "report.json", "--json"], expect=1)
            self.assertIn(result["status"], {"BLOCKED", "INCOMPLETE"})
            self.assertGreaterEqual(result["metrics"]["newBlockingFindings"], 1)
            self.assertGreaterEqual(len(result["metrics"]["missingLockedInvariantIds"]), 1)

    def test_convergence_marks_improving_until_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = self.lock_registry(registry_path, "r2")
            policy = self.policy(root)
            verified = [item["invariantId"] for item in registry["invariants"]]
            baseline = self.write_snapshot(root / "baseline.json", "r1", [self.finding("F-1", "RC-1"), self.finding("F-2", "RC-2")], verified=verified)
            current = self.write_snapshot(root / "current.json", "r2", [self.finding("F-1", "RC-1"), self.finding("F-2", "RC-2", status="CLOSED")], verified=verified)
            improving = run([CONVERGENCE, "--baseline", baseline, "--current", current, "--policy", policy, "--invariant-registry", registry_path, "--out", root / "improving.json", "--json"], expect=1)
            self.assertEqual(improving["status"], "IMPROVING")
            final = self.write_snapshot(root / "final.json", "r3", [self.finding("F-1", "RC-1", status="CLOSED"), self.finding("F-2", "RC-2", status="CLOSED")], verified=verified)
            registry_r3 = self.lock_registry(registry_path, "r3")
            self.assertGreater(registry_r3["metrics"]["locked"], 0)
            passed = run([CONVERGENCE, "--baseline", current, "--current", final, "--policy", policy, "--invariant-registry", registry_path, "--out", root / "pass.json", "--json"])
            self.assertEqual(passed["status"], "PASS")

    def test_convergence_rejects_semantic_and_scope_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = self.lock_registry(registry_path, "r2")
            policy = self.policy(root)
            verified = [item["invariantId"] for item in registry["invariants"]]
            baseline = self.write_snapshot(root / "baseline.json", "r1", [])
            current = self.write_snapshot(root / "current.json", "r2", [
                self.finding("F-1", "RC-1", code="SEMANTIC_DRIFT"),
                self.finding("F-2", "RC-2", code="SCOPE_DRIFT")
            ], verified=verified)
            result = run([CONVERGENCE, "--baseline", baseline, "--current", current, "--policy", policy, "--invariant-registry", registry_path, "--out", root / "report.json", "--json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["metrics"]["semanticDrifts"], 1)
            self.assertEqual(result["metrics"]["scopeDrifts"], 1)

    def test_independent_review_promotes_candidate_and_binds_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = json.loads(registry_path.read_text())
            invariant_id = registry["invariants"][0]["invariantId"]
            review = {
                "schemaVersion": 1,
                "reviewId": "IR-1",
                "workflowId": registry["workflowId"],
                "targetRevision": registry["targetRevision"],
                "registryPath": str(registry_path),
                "registryHash": __import__("hashlib").sha256(registry_path.read_bytes()).hexdigest(),
                "reviewerRole": "delivery-reviewer",
                "independentContext": True,
                "decisions": [{"invariantId": invariant_id, "decision": "ACCEPT", "targetStatus": "LOCKED", "rationale": "Explicit source and invariant are consistent.", "evidenceRefs": ["PRD.md#FR-001"]}],
                "reviewedAt": "2026-11-19T00:00:00+08:00"
            }
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            out = root / "reviewed-registry.json"
            result = run([REVIEW, "--registry", registry_path, "--review", review_path, "--out", out])
            self.assertEqual(result["status"], "PASS")
            updated = json.loads(out.read_text())
            locked = [item for item in updated["invariants"] if item["status"] == "LOCKED"]
            self.assertEqual(len(locked), 1)
            self.assertEqual(locked[0]["lockedBy"], "delivery-reviewer")
            self.assertEqual(Path(updated["source"]["lastReviewResultPath"]), review_path.resolve())

    def test_source_audit_accepts_grounded_lines_and_defers_aggregates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger_path, registry_path = self.fixture(root)
            prd = root / "PRD.md"
            prd.write_text(
                "# Demo\n\n"
                "无编辑权限时不展示编辑入口。\n"
                "条件命中但没有有效参数时不得入队。\n"
                "保持缓冲且不占用坐席。\n",
                encoding="utf-8",
            )
            review_path = root / "review.json"
            audit_path = root / "audit.json"
            result = run([
                AUDIT,
                "--registry", registry_path,
                "--ledger", ledger_path,
                "--review-out", review_path,
                "--audit-out", audit_path,
                "--reviewer-role", "independent-source-checker",
            ])
            self.assertEqual(result["accepted"], 3)
            self.assertEqual(result["deferred"], 0)

            registry = json.loads(registry_path.read_text())
            registry["invariants"][0]["statement"] += "\n这一行不在 PRD 中。"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            result = run([
                AUDIT,
                "--registry", registry_path,
                "--ledger", ledger_path,
                "--review-out", review_path,
                "--audit-out", audit_path,
                "--reviewer-role", "independent-source-checker",
            ])
            self.assertEqual(result["accepted"], 2)
            self.assertEqual(result["deferred"], 1)
            audit = json.loads(audit_path.read_text())
            deferred = [row for row in audit["rows"] if row["decision"] == "DEFER"]
            self.assertEqual(deferred[0]["invariantId"], registry["invariants"][0]["invariantId"])
            self.assertEqual(deferred[0]["missingLineCount"], 1)

    def test_defer_keeps_candidate_and_invalid_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = json.loads(registry_path.read_text())
            invariant_id = registry["invariants"][0]["invariantId"]
            review = {
                "schemaVersion": 1,
                "reviewId": "IR-DEFER",
                "workflowId": registry["workflowId"],
                "targetRevision": registry["targetRevision"],
                "registryPath": str(registry_path),
                "registryHash": __import__("hashlib").sha256(registry_path.read_bytes()).hexdigest(),
                "reviewerRole": "independent-source-checker",
                "independentContext": True,
                "decisions": [{
                    "invariantId": invariant_id,
                    "decision": "DEFER",
                    "targetStatus": "CANDIDATE",
                    "rationale": "The source line could not be located exactly.",
                    "evidenceRefs": ["PRD.md"],
                }],
                "reviewedAt": "2026-11-19T00:00:00+08:00",
            }
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            out = root / "reviewed-registry.json"
            result = run([REVIEW, "--registry", registry_path, "--review", review_path, "--out", out])
            self.assertEqual(result["metrics"]["candidate"], len(registry["invariants"]))
            updated = json.loads(out.read_text())
            deferred = next(item for item in updated["invariants"] if item["invariantId"] == invariant_id)
            self.assertEqual(deferred["status"], "CANDIDATE")

            review["decisions"][0]["targetStatus"] = "ACTIVE"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            result = run([REVIEW, "--registry", registry_path, "--review", review_path, "--out", out], expect=1)
            self.assertEqual(result["status"], "FAIL")

    def test_active_review_does_not_claim_locked_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = json.loads(registry_path.read_text())
            invariant_id = registry["invariants"][0]["invariantId"]
            review = {
                "schemaVersion": 1,
                "reviewId": "IR-ACTIVE",
                "workflowId": registry["workflowId"],
                "targetRevision": registry["targetRevision"],
                "registryPath": str(registry_path),
                "registryHash": __import__("hashlib").sha256(registry_path.read_bytes()).hexdigest(),
                "reviewerRole": "independent-source-checker",
                "independentContext": True,
                "decisions": [{
                    "invariantId": invariant_id,
                    "decision": "ACCEPT",
                    "targetStatus": "ACTIVE",
                    "rationale": "The invariant is grounded but not human-locked.",
                    "evidenceRefs": ["PRD.md"],
                }],
                "reviewedAt": "2026-11-19T00:00:00+08:00",
            }
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            out = root / "reviewed-registry.json"
            run([REVIEW, "--registry", registry_path, "--review", review_path, "--out", out])
            updated = json.loads(out.read_text())
            active = next(item for item in updated["invariants"] if item["invariantId"] == invariant_id)
            self.assertEqual(active["status"], "ACTIVE")
            self.assertNotIn("lockedBy", active)
            self.assertNotIn("lockedAt", active)

    def test_convergence_refuses_vacuous_locked_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            policy = self.policy(root)
            baseline = self.write_snapshot(root / "baseline.json", "r1", [self.finding("F-1", "RC-1")])
            current = self.write_snapshot(root / "current.json", "r1", [self.finding("F-1", "RC-1", status="CLOSED")])
            result = run([
                CONVERGENCE,
                "--baseline", baseline,
                "--current", current,
                "--policy", policy,
                "--invariant-registry", registry_path,
                "--out", root / "report.json",
                "--json",
            ], expect=1)
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(result["metrics"]["lockedInvariantCount"], 0)
            coverage = next(check for check in result["checks"] if check["checkId"] == "CONVERGENCE.LOCKED_INVARIANT_COVERAGE")
            self.assertTrue(coverage["observed"]["vacuous"])

    def test_repeated_root_cause_across_history_blocks_convergence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = self.lock_registry(registry_path, "r3")
            policy = self.policy(root)
            verified = [item["invariantId"] for item in registry["invariants"]]
            baseline = self.write_snapshot(root / "r1.json", "r1", [
                self.finding("F-1", "RC-1"),
                self.finding("F-2", "RC-2"),
            ], verified=verified)
            history = self.write_snapshot(root / "r2.json", "r2", [
                self.finding("F-1", "RC-1"),
                self.finding("F-2", "RC-2", status="CLOSED"),
            ], verified=verified)
            current = self.write_snapshot(root / "r3.json", "r3", [
                self.finding("F-1", "RC-1"),
                self.finding("F-2", "RC-2", status="CLOSED"),
            ], verified=verified)
            result = run([
                CONVERGENCE,
                "--baseline", baseline,
                "--current", current,
                "--history", history,
                "--policy", policy,
                "--invariant-registry", registry_path,
                "--out", root / "report.json",
                "--json",
            ], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["metrics"]["repeatedRootCauseCount"], 1)
            self.assertEqual(result["metrics"]["repeatedRootCauses"][0]["rootCauseId"], "RC-1")

    def test_history_audit_is_forensic_and_not_closure_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            policy = self.policy(root)
            first = self.write_snapshot(root / "r1.json", "r1", [self.finding("F-1", "RC-1")])
            second = self.write_snapshot(root / "r2.json", "r2", [self.finding("F-1", "RC-1")])
            out = root / "history-audit.json"
            result = run([
                HISTORY_AUDIT,
                "--snapshots", first, second,
                "--policy", policy,
                "--invariant-registry", registry_path,
                "--out", out,
            ])
            self.assertEqual(result["mode"], "HISTORICAL_FORENSIC_ONLY")
            self.assertFalse(result["closureEligible"])
            self.assertEqual(result["transitionCount"], 1)

    def test_convergence_rejects_inconsistent_execution_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, registry_path = self.fixture(root)
            registry = self.lock_registry(registry_path, "r2")
            policy = self.policy(root)
            verified = [item["invariantId"] for item in registry["invariants"]]
            baseline = self.write_snapshot(root / "baseline.json", "r1", [self.finding("F-1", "RC-1")], verified=verified)
            current = self.write_snapshot(root / "current.json", "r2", [self.finding("F-1", "RC-1", status="CLOSED")], verified=verified)
            data = json.loads(current.read_text())
            data["executionMetrics"] = {
                "availability": "COMPLETE",
                "elapsedMs": 1000,
                "inputTokens": 10,
                "outputTokens": 5,
                "totalTokens": 99,
                "repairRounds": 1,
                "contextObjectCount": 4,
                "sourceRefs": ["run.json"],
                "capturedAt": "2026-11-19T00:00:00+08:00",
            }
            current.write_text(json.dumps(data), encoding="utf-8")
            result = run([
                CONVERGENCE,
                "--baseline", baseline,
                "--current", current,
                "--policy", policy,
                "--invariant-registry", registry_path,
                "--out", root / "report.json",
                "--json",
            ], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any(reason.startswith("CONVERGENCE.EXECUTION_METRICS_BINDING") for reason in result["blockingReasons"]))


if __name__ == "__main__":
    unittest.main()
