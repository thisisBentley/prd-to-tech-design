import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILD = TOOLS / "build_collaboration_surface.py"
VALIDATE = TOOLS / "validate_collaboration_surface.py"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class CollaborationSurfaceTests(unittest.TestCase):
    def fixture(self, root, *, episode_status="COMPLETE", open_decision=False, no_reviews=False):
        def write(path, data):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        decisions = root / "decisions"
        decision = write(decisions / "D-1.json", {
            "schemaVersion": 1,
            "decisionId": "D-1",
            "workflowId": "WF-CS",
            "owner": "product-owner",
            "ambiguity": "Choose export delivery mode",
            "status": "open" if open_decision else "confirmed",
            "selectedOptionId": None if open_decision else "OPT-A",
        })
        episode = {
            "schemaVersion": 1,
            "episodeId": "EP-0123456789abcdef",
            "workflowId": "WF-CS",
            "requirementId": "REQ-CS",
            "artifactProfile": "PRD_ONLY",
            "revision": "r2",
            "status": episode_status,
            "objective": "Deliver a safe customer export",
            "revisionTimeline": [
                {"eventType": "REVISION", "revision": "r1", "status": "AUDIT_BLOCKED", "sourceRefs": ["audit-r1.json"]},
                {"eventType": "REPAIR", "revision": "r1", "nextRevision": "r2", "status": "AUDIT_PASS", "sourceRefs": ["repair.json"]},
                {"eventType": "FINAL_GATE", "revision": "r2", "status": "PASS", "sourceRefs": ["gate.json"]},
            ],
            "findings": {"status": "AVAILABLE", "metrics": {"total": 1, "openBlocking": 0, "unresolved": 0, "resolved": 1, "repairAttempts": 1}, "openRootCauseIds": [], "findingIds": ["F-1"]},
            "repairs": {"status": "AVAILABLE", "rounds": 1, "cycleStatus": "AUDIT_PASS", "changedArtifacts": ["PRD_DELIVERY.md", "Overview.html"]},
            "costs": {"status": "AVAILABLE", "metricsAvailability": "COMPLETE", "metrics": {"repairRounds": 1, "revisionCount": 2}},
            "consumerAcceptance": {"reportCount": 1, "realCount": 1, "fixtureCount": 0, "statuses": ["PASS"], "humanReviewRequiredCount": 1, "reportIds": ["CAR-1"]},
            "gates": {"finalResult": "PASS", "finalBlockingCount": 0, "finalStatus": "PASS"},
            "evidenceLayers": {"SOURCE_FACT": ["handoff.json", str(decision)], "MEASURED": ["cost.json", "gate.json"], "DERIVED": ["episode.json"], "REFERENCE": [], "INFERENCE": []},
            "humanAdjudication": {"status": "RECORDED" if not open_decision else "PARTIAL", "decisionRefs": [str(decision)], "openDecisionCount": 1 if open_decision else 0},
            "trainingEligibility": {"eligible": False, "status": "BLOCKED", "reasons": ["D14_EPISODE_TRAINING_DISABLED"]},
            "provenance": [{"kind": "HANDOFF", "layer": "SOURCE_FACT", "path": "handoff.json", "sha256": "a" * 64, "revision": "r2"}],
            "evidenceGaps": [],
            "warnings": [],
            "metrics": {"sourceCount": 1, "timelineEvents": 3, "findingsTotal": 1, "openBlockingFindings": 0, "repairRounds": 1, "consumerReports": 1, "revisionCount": 2, "evidenceGaps": 0, "warnings": 0},
            "createdAt": "2026-11-23T00:00:00+00:00",
        }
        episode_path = write(root / "episode.json", episode)
        review = write(root / "reviews" / "review.json", {
            "schemaVersion": 1,
            "reviewRunId": "RR-1",
            "reviewPlanId": "RP-1",
            "workflowId": "WF-CS",
            "producerRole": "prd-producer",
            "reviewerRole": "delivery-reviewer",
            "reviewType": "independent",
            "targetHandoffId": "HO-r2",
            "targetRevision": "r2",
            "independentContext": True,
            "verdict": "ACCEPTED",
            "checks": [],
            "findings": [],
            "blockingCount": 0,
            "evidenceRefs": [str(episode_path)],
            "checkedAt": "2026-11-23T00:00:00+00:00",
            "completionStatus": "complete",
            "reviewerContextId": "ctx-review",
            "reviewerTranscript": "transcript.log",
        })
        return episode_path, decisions, review

    def args(self, episode, decisions, out, markdown, *, no_reviews=False, review_dir=None):
        return [
            BUILD, "--episode", episode, "--review-dir", review_dir or episode.parent / "reviews",
            "--decision-dir", decisions, "--out", out, "--markdown-out", markdown,
        ]

    def test_builds_ready_surface_and_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            episode, decisions, _ = self.fixture(root)
            out = root / "surface.json"
            markdown = root / "surface.md"
            result = run(self.args(episode, decisions, out, markdown))
            self.assertEqual(result["status"], "READY")
            surface = json.loads(out.read_text())
            self.assertEqual(surface["authority"]["gateAuthority"], "UNCHANGED")
            self.assertEqual(surface["authority"]["trainingAuthority"], "NONE")
            self.assertEqual(surface["changeDigest"]["status"], "AVAILABLE")
            self.assertEqual(surface["reviewDigest"]["accepted"], 1)
            self.assertEqual(surface["decisionDigest"]["confirmed"], 1)
            self.assertEqual(surface["riskDigest"]["blocking"], 0)
            self.assertEqual(surface["nextAction"]["status"], "CLEAR")
            body = markdown.read_text()
            for heading in ["Change Digest", "Review Digest", "Decision Digest", "Risk Digest", "Evidence Digest", "Next Action", "Authority"]:
                self.assertIn(heading, body)
            validated = run([VALIDATE, "--surface", out, "--verify-source-hashes"])
            self.assertEqual(validated["status"], "PASS")
            self.assertEqual(validated["surfaceStatus"], "READY")

    def test_open_decision_requires_human_action(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            episode, decisions, _ = self.fixture(root, open_decision=True)
            out = root / "surface.json"
            result = run(self.args(episode, decisions, out, root / "surface.md"))
            self.assertEqual(result["status"], "ACTION_REQUIRED")
            surface = json.loads(out.read_text())
            self.assertGreaterEqual(surface["decisionDigest"]["open"], 1)
            self.assertIn("OBTAIN_HUMAN_DECISION", {item["actionId"] for item in surface["nextAction"]["actions"]})

    def test_blocked_episode_surfaces_blocking_risk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            episode, decisions, _ = self.fixture(root, episode_status="BLOCKED")
            out = root / "surface.json"
            result = run(self.args(episode, decisions, out, root / "surface.md"))
            self.assertEqual(result["status"], "BLOCKED")
            surface = json.loads(out.read_text())
            self.assertIn("RISK-EPISODE-BLOCKED", {item["riskId"] for item in surface["riskDigest"]["items"]})
            self.assertIn("RESOLVE_EPISODE_BLOCKERS", {item["actionId"] for item in surface["nextAction"]["actions"]})

    def test_missing_reviews_becomes_action_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            episode, decisions, _ = self.fixture(root)
            out = root / "surface.json"
            result = run(self.args(episode, decisions, out, root / "surface.md", review_dir=root / "missing-reviews"))
            self.assertEqual(result["status"], "ACTION_REQUIRED")
            surface = json.loads(out.read_text())
            self.assertIn("RUN_INDEPENDENT_REVIEW", {item["actionId"] for item in surface["nextAction"]["actions"]})
            self.assertEqual(surface["reviewDigest"]["status"], "UNAVAILABLE")

    def test_source_hash_drift_blocks_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            episode, decisions, review = self.fixture(root)
            out = root / "surface.json"
            run(self.args(episode, decisions, out, root / "surface.md"))
            review.write_text(review.read_text() + "\n", encoding="utf-8")
            result = run([VALIDATE, "--surface", out, "--verify-source-hashes"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("source hash drift" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
