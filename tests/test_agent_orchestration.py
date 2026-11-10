import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
ORCH = ROOT / SCRIPTS / "orchestrate.py"
VALIDATE = ROOT / SCRIPTS / "validate_agent_contracts.py"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "DEMO-1"
        self.root.mkdir()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.reviews = self.root / "review-files"
        self.reviews.mkdir()

    def run_cli(self, *args, expect=0):
        proc = subprocess.run([sys.executable, str(ORCH), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def write_handoff(self, handoff_id, phase, producer, consumers, artifact_name, revision="r1"):
        artifact = self.artifacts / artifact_name
        artifact.write_text(artifact_name, encoding="utf-8")
        data = {
            "schemaVersion": 1, "handoffId": handoff_id, "workflowId": "WF-DEMO",
            "fromAgent": producer, "toAgents": consumers, "phase": phase, "revision": revision,
            "producerContextId": producer + "-ctx",
            "artifacts": [{"path": str(artifact.relative_to(self.root)), "sha256": sha(artifact), "kind": "test"}],
            "decisions": [], "openFindings": [], "unknowns": [],
            "requestedReviews": ["information-sufficiency" if phase == "discovery" else "prd-completeness"],
            "createdAt": stamp(),
        }
        path = self.root / f"{handoff_id}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def register_handoff(self, path):
        return self.run_cli("register-handoff", "--run-root", self.root, "--file", path)

    def register_review(self, reviewer, target_handoff, target_revision="r1", verdict="ACCEPTED", review_type="consumer", blocking=0, evidence=True, expect=0, reviewer_context=None):
        run_id = f"review-{reviewer}-{target_handoff}"
        plan = {
            "schemaVersion": 1, "reviewPlanId": f"plan-{reviewer}", "reviewRunId": run_id,
            "workflowId": "WF-DEMO", "reviewerRole": reviewer, "targetHandoffId": target_handoff,
            "targetRevision": target_revision,
            "questions": ["Is this handoff sufficient?"], "evidenceTargets": ["artifact"],
            "counterexamples": ["missing source evidence"], "selectedChecks": ["C-1"],
            "createdAt": stamp(),
        }
        plan_path = self.reviews / f"{reviewer}-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        checks = [{"checkId": "C-1", "status": "passed" if verdict == "ACCEPTED" else "failed", "evidenceRefs": ["artifact"] if evidence else [], "observed": "checked", "expected": "sufficient"}]
        findings = [] if verdict in {"ACCEPTED", "ACCEPTED_WITH_ACTIONS"} else [{"findingId": "F-1", "severity": "BLOCKING", "title": "gap", "evidenceRefs": ["artifact"], "impact": "blocked", "closeCondition": "provide evidence", "owner": "producer"}]
        handoff_data = json.loads((self.root / f"{target_handoff}.json").read_text())
        review = {
            "schemaVersion": 1, "reviewRunId": run_id, "reviewPlanId": plan["reviewPlanId"],
            "workflowId": "WF-DEMO", "producerRole": handoff_data["fromAgent"], "reviewerRole": reviewer,
            "reviewType": review_type, "targetHandoffId": target_handoff, "targetRevision": target_revision,
            "independentContext": True, "reviewerContextId": reviewer_context or (reviewer + "-ctx"),
            "reviewerTranscript": str((self.reviews / f"{reviewer}-transcript.log").relative_to(self.root)),
            "verdict": verdict, "completionStatus": "complete",
            "checks": checks, "findings": findings, "blockingCount": blocking,
            "evidenceRefs": ["artifact"] if evidence else [], "checkedAt": stamp(),
        }
        (self.reviews / f"{reviewer}-transcript.log").write_text("review transcript\n", encoding="utf-8")
        review_path = self.reviews / f"{reviewer}-review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        return self.run_cli("register-review", "--run-root", self.root, "--review", review_path, "--plan", plan_path, expect=expect)

    def advance(self):
        return self.run_cli("advance", "--run-root", self.root)

    def test_handoff_profile_propagates_to_state(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo")
        path = self.write_handoff("HO-D-PROFILE", "discovery", "discovery-producer", ["delivery-intake-reviewer"], "brief.md")
        data = json.loads(path.read_text())
        data.update({"artifactProfile": "EXTERNAL_UI_BOUNDARY", "prototypeStatus": "NOT_TRIGGERED", "uiOwnership": "EXTERNAL"})
        path.write_text(json.dumps(data), encoding="utf-8")
        # update artifact hash because the handoff file itself changed, not the artifact
        self.register_handoff(path)
        state = json.loads((self.root / ".agents" / "orchestration.json").read_text())
        self.assertEqual(state["artifactProfile"], "EXTERNAL_UI_BOUNDARY")
        self.assertEqual(state["prototypeStatus"], "NOT_TRIGGERED")
        self.assertEqual(state["uiOwnership"], "EXTERNAL")

    def test_full_workflow_reaches_ready(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo", "--requirement-id", "DEMO-1")
        self.register_handoff(self.write_handoff("HO-D-1", "discovery", "discovery-producer", ["delivery-intake-reviewer"], "brief.md"))
        self.assertEqual(self.advance()["to"], "DELIVERY_INTAKE_REVIEW")
        self.register_review("delivery-intake-reviewer", "HO-D-1")
        self.assertEqual(self.advance()["to"], "DELIVERY_AUTHORING")

        self.register_handoff(self.write_handoff("HO-P-1", "delivery", "delivery-producer", ["delivery-reviewer", "qa-red-team", "tech-prd-diagnostician"], "prd.md"))
        self.advance(); self.assertEqual(self.advance()["to"], "DELIVERY_REVIEW")
        self.register_review("delivery-reviewer", "HO-P-1")
        self.register_review("qa-red-team", "HO-P-1", review_type="independent")
        self.assertEqual(self.advance()["to"], "TECH_PRD_DIAGNOSIS")
        self.register_review("tech-prd-diagnostician", "HO-P-1")
        self.assertEqual(self.advance()["to"], "TECH_AUTHORING")

        self.register_handoff(self.write_handoff("HO-T-1", "tech-solution", "tech-producer", ["tech-reviewer", "product-acceptance-reviewer"], "tech.md"))
        self.advance(); self.assertEqual(self.advance()["to"], "TECH_REVIEW")
        self.register_review("tech-reviewer", "HO-T-1", review_type="independent")
        self.assertEqual(self.advance()["to"], "PRODUCT_ACCEPTANCE_REVIEW")
        self.register_review("product-acceptance-reviewer", "HO-T-1")
        self.assertEqual(self.advance()["to"], "FINAL_GATEKEEPER")
        result = self.run_cli("gatekeeper", "--run-root", self.root)
        self.assertEqual(result["status"], "READY")
        self.run_cli("validate", "--run-root", self.root)

    def test_intake_return_moves_back_to_discovery(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo")
        self.register_handoff(self.write_handoff("HO-D-1", "discovery", "discovery-producer", ["delivery-intake-reviewer"], "brief.md"))
        self.advance()
        self.register_review("delivery-intake-reviewer", "HO-D-1", verdict="RETURNED", blocking=1)
        result = self.advance()
        self.assertEqual(result["status"], "RETURNED")
        self.assertEqual(result["to"], "DISCOVERY_AUTHORING")

    def test_accepted_review_without_evidence_fails_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            path.write_text(json.dumps({
                "schemaVersion": 1, "reviewRunId": "r", "reviewPlanId": "p", "workflowId": "w",
                "producerRole": "delivery-producer", "reviewerRole": "delivery-reviewer",
                "reviewType": "independent", "targetHandoffId": "h", "targetRevision": "r1",
                "independentContext": True, "reviewerContextId": "rev-ctx", "reviewerTranscript": "transcript.log",
                "verdict": "ACCEPTED", "completionStatus": "complete",
                "checks": [{"checkId": "c", "status": "passed", "evidenceRefs": [], "observed": "x", "expected": "y"}],
                "findings": [], "blockingCount": 0, "evidenceRefs": [], "checkedAt": stamp(),
            }), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(VALIDATE), str(path)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("evidenceRefs", proc.stdout)

    def test_self_review_is_rejected(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo")
        self.register_handoff(self.write_handoff("HO-D-1", "discovery", "discovery-producer", ["delivery-intake-reviewer"], "brief.md"))
        self.advance()
        result = self.register_review("discovery-producer", "HO-D-1", review_type="independent", expect=1)
        # The reviewer is not a declared consumer and is also the producer.
        self.assertEqual(result["status"], "FAIL")

    def test_same_context_review_is_rejected(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo")
        self.register_handoff(self.write_handoff("HO-D-1", "discovery", "discovery-producer", ["delivery-intake-reviewer"], "brief.md"))
        self.advance()
        result = self.register_review("delivery-intake-reviewer", "HO-D-1", reviewer_context="discovery-producer-ctx", expect=1)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("distinct from the producer context" in e for e in result["errors"]))

    def test_research_record_registration_and_decision_precondition(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo")
        record = {
            "schemaVersion": 1, "researchId": "R-1", "workflowId": "WF-DEMO", "clue": "existing behavior",
            "clueType": "HISTORICAL_IMPLEMENTATION",
            "researchPlan": [{"source": "JIRA", "query": "existing behavior", "purpose": "find precedent"}],
            "sourcesChecked": [{"source": "JIRA", "status": "AVAILABLE", "evidenceRefs": ["jira://DEMO-1"]}],
            "findings": [{"claim": "history confirms the field mapping", "evidenceRefs": ["jira://DEMO-1"], "confidence": "HIGH"}],
            "verdict": "FACT_RESOLVED", "decisionRequired": False, "evidenceRefs": ["jira://DEMO-1"],
            "createdAt": stamp(),
        }
        path = self.reviews / "research.json"; path.write_text(json.dumps(record), encoding="utf-8")
        result = self.run_cli("register-research", "--run-root", self.root, "--file", path)
        self.assertEqual(result["status"], "REGISTERED")
        state = json.loads((self.root / ".agents" / "orchestration.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["researchRecords"]), 1)
        card = {
            "schemaVersion": 1, "decisionId": "D-1", "workflowId": "WF-DEMO", "reviewerRole": "delivery-reviewer",
            "businessScenario": "Scope changes", "currentFacts": ["Research found no unique business outcome"],
            "ambiguity": "Scope is unresolved",
            "options": [
                {"optionId": "A", "label": "A", "result": "A", "impact": "A", "reversibility": "reversible"},
                {"optionId": "B", "label": "B", "result": "B", "impact": "B", "reversibility": "reversible"},
            ],
            "recommendation": "Choose A", "defaultAndRisk": "A is safe", "owner": "product",
            "closeCondition": "Choose an option", "researchRecordPath": "research.json",
            "researchVerdict": "NEEDS_BUSINESS_DECISION", "researchEvidenceRefs": ["jira://DEMO-1"],
            "whyDecisionRequired": "Existing sources do not define the business result.", "status": "open", "createdAt": stamp(),
        }
        path = self.reviews / "decision.json"; path.write_text(json.dumps(card), encoding="utf-8")
        self.run_cli("register-decision", "--run-root", self.root, "--file", path)
        result = self.advance()
        self.assertEqual(result["status"], "BLOCKED")

    def test_open_decision_blocks_advance(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo")
        card = {
            "schemaVersion": 1, "decisionId": "D-1", "workflowId": "WF-DEMO", "reviewerRole": "delivery-reviewer",
            "businessScenario": "Scope changes", "currentFacts": ["Two options exist"],
            "ambiguity": "Scope is unresolved",
            "options": [
                {"optionId": "A", "label": "A", "result": "A", "impact": "A", "reversibility": "reversible"},
                {"optionId": "B", "label": "B", "result": "B", "impact": "B", "reversibility": "reversible"},
            ],
            "recommendation": "Choose A", "defaultAndRisk": "A is safe", "owner": "product",
            "closeCondition": "Choose an option", "researchRecordPath": "research-record.json",
            "researchVerdict": "NEEDS_BUSINESS_DECISION", "researchEvidenceRefs": ["jira://EXAMPLE"],
            "whyDecisionRequired": "Existing sources do not define the business result.", "status": "open", "createdAt": stamp(),
        }
        path = self.reviews / "decision.json"; path.write_text(json.dumps(card), encoding="utf-8")
        self.run_cli("register-decision", "--run-root", self.root, "--file", path)
        result = self.advance()
        self.assertEqual(result["status"], "BLOCKED")

    def test_review_plan_target_mismatch_fails(self):
        self.run_cli("init", "--run-root", self.root, "--workflow-id", "WF-DEMO", "--requirement-name", "Demo")
        self.register_handoff(self.write_handoff("HO-D-1", "discovery", "discovery-producer", ["delivery-intake-reviewer"], "brief.md"))
        self.advance()
        plan = {
            "schemaVersion": 1, "reviewPlanId": "p", "reviewRunId": "r", "workflowId": "WF-DEMO",
            "reviewerRole": "delivery-intake-reviewer", "targetHandoffId": "HO-D-1", "targetRevision": "r2",
            "questions": ["q"], "evidenceTargets": ["e"], "counterexamples": [], "selectedChecks": ["c"], "createdAt": stamp(),
        }
        review = {
            "schemaVersion": 1, "reviewRunId": "r", "reviewPlanId": "p", "workflowId": "WF-DEMO",
            "producerRole": "discovery-producer", "reviewerRole": "delivery-intake-reviewer", "reviewType": "consumer",
            "targetHandoffId": "HO-D-1", "targetRevision": "r1", "independentContext": True,
            "reviewerContextId": "reviewer-ctx", "reviewerTranscript": "review-transcript.log",
            "verdict": "ACCEPTED", "completionStatus": "complete",
            "checks": [{"checkId": "c", "status": "passed", "evidenceRefs": ["e"], "observed": "x", "expected": "y"}],
            "findings": [], "blockingCount": 0, "evidenceRefs": ["e"], "checkedAt": stamp(),
        }
        pp = self.reviews / "p.json"; rp = self.reviews / "r.json"
        (self.reviews / "review-transcript.log").write_text("review\n", encoding="utf-8")
        pp.write_text(json.dumps(plan), encoding="utf-8"); rp.write_text(json.dumps(review), encoding="utf-8")
        result = self.run_cli("register-review", "--run-root", self.root, "--review", rp, "--plan", pp, expect=1)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("targetRevision" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
