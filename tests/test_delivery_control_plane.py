import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "validate_delivery_control_plane.py"
ORCHESTRATE = ROOT / SCRIPTS / "orchestrate.py"
SCHEMA = ROOT / ("references" if ROOT.name == "ai-native-delivery" else "schemas") / "state-consistency-report.schema.json"
sys.path.insert(0, str(ROOT / SCRIPTS))
from validate_json_schemas import validate as validate_schema


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class DeliveryControlPlaneTests(unittest.TestCase):
    def run_tool(self, root: Path, expect: int = 0) -> dict:
        out = root / ".agents" / "quality" / "delivery-control-plane.json"
        process = subprocess.run(
            [sys.executable, str(TOOL), "--run-root", str(root), "--out", str(out)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(out.read_text(encoding="utf-8"))

    def setup_run(self, td: str, stage: str = "DELIVERY_SEALED"):
        root = Path(td) / "run"
        bundle = root / "01-delivery"
        dd = bundle / ".delivery"
        frozen = dd / "candidate-revisions" / "r1"
        frozen.mkdir(parents=True)
        artifact = root / "handoff-artifact.md"
        artifact.write_text("delivery evidence\n", encoding="utf-8")
        artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        save(dd / "state.json", {
            "schemaVersion": 1,
            "workflowId": "WF-CONTROL",
            "phase2": {"status": "DESIGN_READY", "revision": "r1", "candidateRevision": "r1", "bundleId": "WF-CONTROL-delivery-r1"},
        })
        save(dd / "candidate-seal.json", {"bundleId": "WF-CONTROL-delivery-r1", "revision": "r1", "frozenCopy": ".delivery/candidate-revisions/r1"})
        save(dd / "final-seal.json", {"bundleId": "WF-CONTROL-delivery-r1", "revision": "r1", "status": "DESIGN_READY"})
        save(root / ".agents" / "delivery-readiness.json", {"status": "DESIGN_READY", "revision": "r1", "designReady": True})
        handoff = {
            "schemaVersion": 1,
            "handoffId": "WF-CONTROL-delivery-r1",
            "workflowId": "WF-CONTROL",
            "fromAgent": "delivery-producer",
            "toAgents": ["delivery-reviewer"],
            "phase": "delivery",
            "revision": "r1",
            "artifacts": [{"path": "handoff-artifact.md", "sha256": artifact_hash, "kind": "delivery-evidence"}],
            "decisions": [],
            "openFindings": [],
            "unknowns": [],
            "requestedReviews": ["delivery-bundle"],
            "createdAt": "2026-11-17T00:00:00Z",
            "producerContextId": "ctx-delivery-r1",
        }
        handoff_path = root / ".agents" / "handoffs" / "delivery-r1.json"
        save(handoff_path, handoff)
        save(root / ".agents" / "orchestration.json", {
            "schemaVersion": 1,
            "workflowId": "WF-CONTROL",
            "requirement": {"name": "Control Plane Demo"},
            "status": "IN_PROGRESS",
            "currentStage": stage,
            "createdAt": "2026-11-17T00:00:00Z",
            "updatedAt": "2026-11-17T00:00:00Z",
            "handoffs": [".agents/handoffs/delivery-r1.json"],
            "reviewPlans": [],
            "reviews": [],
            "decisions": [],
            "escalations": [],
            "researchRecords": [],
            "history": [],
        })
        return root, handoff_path

    def test_consistent_control_plane_passes_and_matches_schema(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = self.setup_run(td)
            report = self.run_tool(root)
            self.assertEqual(report["status"], "PASS")
            errors = validate_schema(report, json.loads(SCHEMA.read_text()), json.loads(SCHEMA.read_text()))
            self.assertEqual(errors, [])

    def test_design_ready_delivery_blocks_when_orchestration_is_discovery_authoring(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = self.setup_run(td, stage="DISCOVERY_AUTHORING")
            report = self.run_tool(root, expect=1)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("ORCHESTRATION_STAGE_MISMATCH", {item["code"] for item in report["conflicts"]})
            self.assertTrue(any(item["checkId"] == "STATE.ORCHESTRATION_STAGE" and item["status"] == "failed" for item in report["checks"]))

    def test_unregistered_handoff_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = self.setup_run(td)
            state_path = root / ".agents" / "orchestration.json"
            state = json.loads(state_path.read_text())
            state["handoffs"] = []
            save(state_path, state)
            report = self.run_tool(root, expect=1)
            self.assertIn("HANDOFF_NOT_REGISTERED", {item["code"] for item in report["conflicts"]})

    def test_stale_handoff_revision_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root, handoff = self.setup_run(td)
            data = json.loads(handoff.read_text())
            data["revision"] = "r0"
            save(handoff, data)
            report = self.run_tool(root, expect=1)
            self.assertIn("REVISION_MISMATCH", {item["code"] for item in report["conflicts"]})

    def test_sync_delivery_closes_discovery_authoring_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root, handoff = self.setup_run(td, stage="DISCOVERY_AUTHORING")
            state_path = root / ".agents" / "orchestration.json"
            state = json.loads(state_path.read_text())
            state["handoffs"] = []
            save(state_path, state)
            process = subprocess.run(
                [sys.executable, str(ORCHESTRATE), "sync-delivery", "--run-root", str(root), "--handoff", str(handoff), "--revision", "r1"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            synced = json.loads(process.stdout)
            self.assertEqual(synced["status"], "PASS")
            self.assertEqual(synced["currentStage"], "DELIVERY_SEALED")
            report = self.run_tool(root)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["orchestrationState"]["currentStage"], "DELIVERY_SEALED")


if __name__ == "__main__":
    unittest.main()
