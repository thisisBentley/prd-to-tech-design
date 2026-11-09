import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
PAIR = ROOT / SCRIPTS / "build_artifact_pair.py"
GATE = ROOT / SCRIPTS / "validate_artifact_consistency.py"


class ArtifactConsistencyTests(unittest.TestCase):
    def run_cli(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def setup_artifacts(self, root, prd_text, html_ids, manifest_ids, overview_revision="r3", prd_revision="r3", prototype_revision="r3"):
        prd = root / "PRD_DELIVERY.md"
        prototype = root / "Prototype.html"
        overview = root / "Overview.html"
        manifest = root / "prototype-manifest.json"
        pair = root / "artifact-pair.json"
        prd.write_text(prd_text, encoding="utf-8")
        bindings = {ui_id: (frs, acs) for ui_id, frs, acs in manifest_ids}
        prototype.write_text("\n".join(
            f'<div data-ai-id="{item}" data-ai-fr="{",".join(bindings.get(item, ([], []))[0])}" data-ai-ac="{",".join(bindings.get(item, ([], []))[1])}">{item}</div>'
            for item in html_ids
        ), encoding="utf-8")
        overview.write_text("<html>overview</html>", encoding="utf-8")
        elements = []
        for ui_id, frs, acs in manifest_ids:
            elements.append({"uiElementId": ui_id, "frIds": frs, "acIds": acs, "visibleLabel": ui_id, "states": ["default"]})
        manifest.write_text(json.dumps({
            "schemaVersion": 1, "manifestId": "M-1", "workflowId": "WF-1", "prototypeRevision": prototype_revision,
            "prototypePath": str(prototype.resolve()), "prototypeHash": hashlib.sha256(prototype.read_bytes()).hexdigest(),
            "elements": elements, "createdAt": "2026-11-09T00:00:00Z",
        }), encoding="utf-8")
        self.run_cli(PAIR, "--workflow-id", "WF-1", "--artifact-profile", "PRD_PLUS_PROTOTYPE", "--prd", prd, "--prototype", prototype, "--prd-revision", prd_revision, "--prototype-revision", prototype_revision, "--overview", overview, "--overview-revision", overview_revision, "--out", pair)
        return pair, prd, prototype, manifest, overview

    def test_reconciled_pair_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
            )
            out = root / "consistency.json"
            result = self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--overview", overview, "--out", out)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["blockingCount"], 0)

    def test_deleted_ui_still_present_in_prd_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- FR-008: Approval comment\n- AC-014: Approval comment persists\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
            )
            previous = root / "previous.json"
            previous.write_text(json.dumps({
                "schemaVersion": 1, "manifestId": "M-0", "workflowId": "WF-1", "prototypeRevision": "r2",
                "prototypePath": str(prototype.resolve()), "prototypeHash": hashlib.sha256(prototype.read_bytes()).hexdigest(),
                "elements": [
                    {"uiElementId": "UI-submit", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Submit", "states": ["default"]},
                    {"uiElementId": "UI-approval-comment", "frIds": ["FR-008"], "acIds": ["AC-014"], "visibleLabel": "Approval comment", "states": ["default"]},
                ], "createdAt": "2026-11-09T00:00:00Z",
            }), encoding="utf-8")
            out = root / "consistency.json"
            result = self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--previous-manifest", previous, "--overview", overview, "--out", out, expect=1)
            self.assertEqual(result["status"], "NEEDS_FIX")
            data = json.loads(out.read_text(encoding="utf-8"))
            finding = next(item for item in data["findings"] if item["type"] == "DELETED_UI_ELEMENT_STILL_PRESENT_IN_PRD")
            self.assertEqual(finding["uiElementId"], "UI-approval-comment")
            self.assertEqual(finding["frIds"], ["FR-008"])
            self.assertEqual(finding["acIds"], ["AC-014"])
            self.assertEqual(finding["owner"], "prd-agent")

    def test_deleted_ui_reconciled_in_prd_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
            )
            previous = root / "previous.json"
            previous.write_text(json.dumps({
                "schemaVersion": 1, "manifestId": "M-0", "workflowId": "WF-1", "prototypeRevision": "r2",
                "prototypePath": str(prototype.resolve()), "prototypeHash": hashlib.sha256(prototype.read_bytes()).hexdigest(),
                "elements": [
                    {"uiElementId": "UI-submit", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Submit", "states": ["default"]},
                    {"uiElementId": "UI-approval-comment", "frIds": ["FR-008"], "acIds": ["AC-014"], "visibleLabel": "Approval comment", "states": ["default"]},
                ], "createdAt": "2026-11-09T00:00:00Z",
            }), encoding="utf-8")
            out = root / "consistency.json"
            result = self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--previous-manifest", previous, "--overview", overview, "--out", out)
            self.assertEqual(result["status"], "PASS")

    def test_stale_revisions_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
                prd_revision="r4",
                prototype_revision="r3",
            )
            pair_data = json.loads(pair.read_text(encoding="utf-8"))
            self.assertEqual(pair_data["pairStatus"], "RESYNC_REQUIRED")
            out = root / "consistency.json"
            result = self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--overview", overview, "--out", out, expect=1)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["type"] == "STALE_ARTIFACT_PAIR" for item in data["findings"]))

    def test_prd_required_ui_missing_from_prototype_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n- UI-cancel\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
            )
            out = root / "consistency.json"
            self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--overview", overview, "--out", out, expect=1)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["type"] == "MISSING_UI_ELEMENT" and item.get("uiElementId") == "UI-cancel" for item in data["findings"]))

    def test_semantic_delta_without_reconciliation_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
            )
            delta = root / "delta.json"
            delta.write_text(json.dumps({
                "schemaVersion": 1, "deltaId": "D-1", "workflowId": "WF-1", "fromPrototypeRevision": "r2", "toPrototypeRevision": "r3",
                "changeType": "SEMANTIC", "requiresPrdReconciliation": True,
                "changes": [{"action": "DELETE", "uiElementId": "UI-approval-comment", "linkedFeatureIds": ["FR-008"], "linkedAcIds": ["AC-014"], "reason": "removed", "evidenceRefs": ["prototype"]}],
                "createdAt": "2026-11-09T00:00:00Z",
            }), encoding="utf-8")
            out = root / "consistency.json"
            self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--delta", delta, "--overview", overview, "--out", out, expect=1)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["type"] == "UNRECONCILED_PROTOTYPE_DELTA" for item in data["findings"]))

    def test_synced_reconciliation_closes_semantic_delta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
            )
            delta = root / "delta.json"
            delta.write_text(json.dumps({
                "schemaVersion": 1, "deltaId": "D-2", "workflowId": "WF-1", "fromPrototypeRevision": "r2", "toPrototypeRevision": "r3",
                "changeType": "SEMANTIC", "requiresPrdReconciliation": True,
                "changes": [{"action": "DELETE", "uiElementId": "UI-approval-comment", "linkedFeatureIds": ["FR-008"], "linkedAcIds": ["AC-014"], "reason": "removed", "evidenceRefs": ["prototype"]}],
                "createdAt": "2026-11-09T00:00:00Z",
            }), encoding="utf-8")
            reconciliation = root / "reconciliation.json"
            reconciliation.write_text(json.dumps({
                "schemaVersion": 1, "reconciliationId": "R-2", "workflowId": "WF-1", "sourcePrototypeDeltaId": "D-2",
                "fromPrdRevision": "r2", "toPrdRevision": "r3", "status": "SYNCED",
                "updatedFeatures": [{"frId": "FR-008", "action": "DELETE"}],
                "updatedAcceptanceCriteria": [{"acId": "AC-014", "action": "DELETE"}],
                "unresolvedDeltas": [], "evidenceRefs": ["delta"], "createdAt": "2026-11-09T00:00:00Z",
            }), encoding="utf-8")
            out = root / "consistency.json"
            result = self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--delta", delta, "--reconciliation", reconciliation, "--overview", overview, "--out", out)
            self.assertEqual(result["status"], "PASS")

    def test_strict_copy_detects_prd_prototype_label_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-001"], ["AC-001"])],
            )
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["elements"][0]["visibleLabel"] = "Send now"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            out = root / "consistency.json"
            self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--overview", overview, "--strict-copy", "--out", out, expect=1)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["type"] == "INCONSISTENT_BUSINESS_COPY" for item in result["findings"]))

    def test_orphan_manifest_binding_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, prd, prototype, manifest, overview = self.setup_artifacts(
                root,
                "# PRD\n\n- FR-001: Submit expense\n- AC-001: Submission succeeds\n- UI-submit\n",
                ["UI-submit"],
                [("UI-submit", ["FR-999"], ["AC-999"])],
            )
            out = root / "consistency.json"
            result = self.run_cli(GATE, "--pair", pair, "--prd", prd, "--prototype", prototype, "--manifest", manifest, "--overview", overview, "--out", out, expect=1)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["type"] == "ORPHAN_UI_ELEMENT" for item in data["findings"]))


if __name__ == "__main__":
    unittest.main()
