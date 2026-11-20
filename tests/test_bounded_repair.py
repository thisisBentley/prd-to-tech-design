import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
EVAL = TOOLS / "evaluate_bounded_repair.py"
POLICY = ROOT / "config" / "trust-kernel" / "bounded-repair-policy-v1.json"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def run(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


class BoundedRepairTests(unittest.TestCase):
    def batch(self, root):
        data = {
            "schemaVersion": 1,
            "batchType": "CHANGE_SET_BATCH",
            "batchId": "CHANGE-SET-BATCH-TEST",
            "workflowId": "WF-REPAIR-1",
            "targetRevision": "r1",
            "status": "READY_FOR_REPAIR",
            "sourceFindings": ["review.json"],
            "policy": {"path": "change-set-policy.json", "policyId": "POLICY-1"},
            "metrics": {"blockingFindings": 2, "coveredBlockingFindings": 2, "changeSets": 2, "plannedChangeSets": 2, "blockedChangeSets": 0, "businessRevisionChangeSets": 1, "mechanicalChangeSets": 0},
            "findings": [],
            "createdAt": "2026-11-20T00:00:00+00:00",
            "changeSets": [
                {
                    "changeSetId": "CHANGE-SET-A",
                    "rootCauseId": "ROOT-A",
                    "findingIds": ["F-A"],
                    "classification": "SPEC_MISSING",
                    "repairTrack": "BUSINESS_REVISION",
                    "businessRevisionRequired": True,
                    "ownerRole": "prd-producer",
                    "affectedArtifacts": [{"path": "PRD_DELIVERY.md", "artifactType": "PRD", "reason": "missing rule"}],
                    "verificationPlan": [{"checkId": "CHECK-A", "kind": "SEMANTIC", "description": "verify A", "required": True}],
                    "budget": {"maxAffectedArtifacts": 4, "maxFindings": 16, "maxRepairRounds": 2, "maxChangedLines": 600},
                    "closeConditions": ["close A"],
                    "expectedInvariants": ["invariant A"],
                    "sourceRefs": ["review.json"],
                    "status": "PLANNED",
                },
                {
                    "changeSetId": "CHANGE-SET-B",
                    "rootCauseId": "ROOT-B",
                    "findingIds": ["F-B"],
                    "classification": "ARTIFACT_DRIFT",
                    "repairTrack": "ARTIFACT_SYNC",
                    "businessRevisionRequired": False,
                    "ownerRole": "projection-repair-agent",
                    "affectedArtifacts": [{"path": "Overview.html", "artifactType": "OVERVIEW", "reason": "drift"}],
                    "verificationPlan": [{"checkId": "CHECK-B", "kind": "PROJECTION", "description": "verify B", "required": True}],
                    "budget": {"maxAffectedArtifacts": 6, "maxFindings": 20, "maxRepairRounds": 2, "maxChangedLines": 800},
                    "closeConditions": ["close B"],
                    "expectedInvariants": ["invariant B"],
                    "sourceRefs": ["review.json"],
                    "status": "PLANNED",
                },
            ],
        }
        path = root / "change-set-batch.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def round(self, root, index, changes, *, status="PASS", open_blocking=0, closed=2, new_blocking=0, open_roots=None, score=1.0, baseline_score=0.0, baseline_open=2, changed=None, business_revision=None, independent=True, external="NOT_RUN", producer_context=None, verifier_context=None, roles=None):
        data = {
            "schemaVersion": 1,
            "roundId": f"ROUND-{index}",
            "roundIndex": index,
            "revision": f"r{index + 1}",
            "changeSetIds": changes,
            "patch": {
                "status": "PASS",
                "beforeHash": SHA_A if index == 1 else SHA_B,
                "afterHash": SHA_B if index == 1 else SHA_C,
                "changedArtifacts": changed or ([item for change in changes for item in (["PRD_DELIVERY.md"] if change == "CHANGE-SET-A" else ["Overview.html"])]),
            },
            "rebuild": {"status": "PASS", "evidenceRefs": [f"round-{index}-rebuild.json"]},
            "verification": {
                "status": status,
                "producerRole": (roles or ("prd-producer", "delivery-reviewer"))[0],
                "verifierRole": (roles or ("prd-producer", "delivery-reviewer"))[1],
                "producerContextId": producer_context or f"producer-{index}",
                "verifierContextId": verifier_context or f"verifier-{index}",
                "independentContext": independent,
                "openBlocking": open_blocking,
                "closedFindings": closed,
                "newBlockingFindings": new_blocking,
                "openRootCauseIds": open_roots or [],
                "baselineOpenBlocking": baseline_open,
                "baselineWeightedScore": baseline_score,
                "weightedScore": score,
                "externalGateStatus": external,
            },
            "businessRevisionCreated": any(item == "CHANGE-SET-A" for item in changes) if business_revision is None else business_revision,
        }
        path = root / f"round-{index}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def evaluate(self, root, batch, rounds, expect=0):
        args = [EVAL, "--change-set-batch", batch, "--policy", POLICY]
        for path in rounds:
            args.extend(["--round", path])
        args.extend(["--out", root / "bounded-run.json"])
        result = run(args, expect=expect)
        return result, json.loads((root / "bounded-run.json").read_text(encoding="utf-8"))

    def test_pass_returns_ready_for_human_submission_but_never_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["CHANGE-SET-A", "CHANGE-SET-B"])
            result, payload = self.evaluate(root, batch, [item])
            self.assertEqual(result["status"], "READY_FOR_HUMAN_SUBMISSION")
            self.assertEqual(payload["state"], "READY_FOR_HUMAN_SUBMISSION")
            self.assertFalse(payload["closureEligible"])
            self.assertFalse(payload["externalSubmissionAllowed"])
            self.assertEqual(payload["roundEvaluations"][0]["outcome"], "PASS")

    def test_self_verification_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["CHANGE-SET-A", "CHANGE-SET-B"], independent=False, verifier_context="producer-1")
            result, payload = self.evaluate(root, batch, [item], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(payload["metrics"]["independentVerificationFailures"], 1)

    def test_out_of_scope_patch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["CHANGE-SET-A"], changed=["PRD_DELIVERY.md", "Unrelated.html"], open_roots=["ROOT-B"])
            result, payload = self.evaluate(root, batch, [item], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(payload["metrics"]["scopeViolations"], 1)

    def test_non_business_change_cannot_create_business_revision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["CHANGE-SET-B"], open_roots=["ROOT-A"], business_revision=True)
            result, payload = self.evaluate(root, batch, [item], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("business revision" in reason for reason in payload["roundEvaluations"][0]["reasons"]))

    def test_regression_stops_immediately(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["CHANGE-SET-A"], status="FAIL", open_blocking=3, new_blocking=1, open_roots=["ROOT-A"], score=0.1)
            result, payload = self.evaluate(root, batch, [item], expect=1)
            self.assertEqual(result["status"], "REGRESSED")

    def test_same_root_cause_across_two_rounds_stalls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            first = self.round(root, 1, ["CHANGE-SET-A"], status="FAIL", open_blocking=1, closed=1, open_roots=["ROOT-A"], score=0.5)
            second = self.round(root, 2, ["CHANGE-SET-B"], status="FAIL", open_blocking=1, closed=1, open_roots=["ROOT-A"], score=0.8)
            result, payload = self.evaluate(root, batch, [first, second], expect=1)
            self.assertEqual(result["status"], "STALLED")
            self.assertEqual(payload["metrics"]["repeatedRootCauseIds"], ["ROOT-A"])

    def test_improving_two_rounds_without_pass_reaches_max_rounds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            first = self.round(root, 1, ["CHANGE-SET-A"], status="FAIL", open_blocking=2, closed=1, open_roots=["ROOT-A"], score=0.5)
            second = self.round(root, 2, ["CHANGE-SET-B"], status="FAIL", open_blocking=1, closed=1, open_roots=["ROOT-B"], score=0.8)
            result, payload = self.evaluate(root, batch, [first, second], expect=1)
            self.assertEqual(result["status"], "MAX_ROUNDS_REACHED")
            self.assertEqual(payload["metrics"]["coveredChangeSets"], 2)

    def test_no_improvement_stalls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["CHANGE-SET-A"], status="FAIL", open_blocking=2, closed=0, open_roots=["ROOT-A"], score=0.0)
            result, payload = self.evaluate(root, batch, [item], expect=1)
            self.assertEqual(result["status"], "STALLED")

    def test_external_gate_failure_cannot_be_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["CHANGE-SET-A", "CHANGE-SET-B"], external="FAIL")
            result, payload = self.evaluate(root, batch, [item], expect=1)
            self.assertEqual(result["status"], "BLOCKED")

    def test_unknown_change_set_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = self.batch(root)
            item = self.round(root, 1, ["UNKNOWN-CHANGE-SET"])
            result, payload = self.evaluate(root, batch, [item], expect=1)
            self.assertEqual(result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
