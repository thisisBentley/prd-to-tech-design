import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "rebuild_derived_evidence.py"
SCHEMA = ROOT / ("references" if ROOT.name == "ai-native-delivery" else "schemas") / "derived-rebuild-manifest.schema.json"
sys.path.insert(0, str(ROOT / SCRIPTS))
from validate_json_schemas import validate as validate_schema


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class DerivedEvidenceRebuildTests(unittest.TestCase):
    def make_source(self, tmp: Path) -> Path:
        bundle = tmp / "01-delivery"
        source = bundle / ".delivery" / "candidate-revisions" / "r1"
        source.mkdir(parents=True)
        doc = source / "Doc.md"
        doc.write_text("# Contract\n\nA stable requirement.\n", encoding="utf-8")
        save(source / "requirements.json", {"schemaVersion": 1, "revision": "r1", "requirements": []})
        save(source / ".delivery" / "candidate-seal.json", {
            "schemaVersion": 1,
            "workflowId": "WF-REBUILD",
            "revision": "r1",
            "frozenCopy": ".delivery/candidate-revisions/r1",
            "artifactProfile": "PRD_ONLY",
            "prototypeStatus": "NOT_TRIGGERED",
        })
        save(source / ".delivery" / "semantic-consistency-input.json", {
            "schemaVersion": 1,
            "workflowId": "WF-REBUILD",
            "targetRevision": "r1",
            "producerRole": "prd-producer",
            "artifacts": [{"artifactId": "doc", "domain": "BUSINESS", "path": str(doc), "sha256": hashlib.sha256(doc.read_bytes()).hexdigest()}],
            "terminologyClaims": [{"termId": "T-1", "canonicalName": "Contract", "usedName": "Contract", "usage": "NEW_TERM", "grounding": "GROUNDED", "evidenceRefs": [f"{doc}#L1-L1"]}],
            "capabilityClaims": [{"claimId": "C-1", "capabilityId": "CAP-1", "statement": "New contract", "declaredStatus": "NEW", "verificationStatus": "VERIFIED_NEW", "sourceRefs": [f"{doc}#L1-L1"], "verificationEvidenceRefs": [f"{doc}#L1-L1"]}],
            "stateAssumptions": [{"stateId": "default", "assumedBy": "PRD", "reachableFrom": ["entry"], "preconditionDefined": True, "evidenceRefs": [f"{doc}#L1-L1"]}],
            "permissionEdges": [{"edgeId": "P-1", "role": "owner", "action": "view", "resource": "contract", "decision": "ALLOWED", "evidenceRefs": [f"{doc}#L1-L1"]}],
            "crossArtifactClaims": [{"claimId": "X-1", "topic": "contract", "businessValue": "contract", "interactionValue": "contract", "status": "EQUAL", "authorityDomain": "BUSINESS", "evidenceRefs": [f"{doc}#L1-L1"]}],
            "businessAssertions": [{"assertionId": "A-1", "statement": "A stable requirement.", "sourceType": "REQUIREMENT", "evidenceRefs": [f"{doc}#L1-L1"], "coveredIds": ["FR-001"]}],
            "interactionElements": [],
        })
        save(bundle / ".delivery" / "state.json", {"schemaVersion": 1, "workflowId": "WF-REBUILD", "phase2": {"revision": "r1"}})
        return bundle

    def test_rebuild_rewrites_refs_and_emits_clean_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle = self.make_source(tmp)
            manifest_path = tmp / "manifest.json"
            process = subprocess.run([
                sys.executable, str(TOOL), "--bundle", str(bundle), "--source-revision", "r1",
                "--target-revision", "r2", "--manifest-out", str(manifest_path),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(manifest["targetRevision"], "r2")
            self.assertEqual(manifest["activeEvidenceScan"]["staleFindingCount"], 0)
            requirements = json.loads((bundle / ".delivery" / "candidate-revisions" / "r2" / "requirements.json").read_text())
            self.assertEqual(requirements["revision"], "r2")
            semantic = json.loads((bundle / ".delivery" / "candidate-revisions" / "r2" / ".delivery" / "semantic-consistency-input.json").read_text())
            self.assertEqual(semantic["targetRevision"], "r2")
            ref = semantic["crossArtifactClaims"][0]["evidenceRefs"][0]
            self.assertIn("candidate-revisions/r2/Doc.md#L1", ref)
            schema = json.loads(SCHEMA.read_text())
            self.assertEqual(validate_schema(manifest, schema, schema), [])

    def test_line_fragment_maps_through_stable_html_anchor(self):
        from rebuild_derived_evidence import map_fragment
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            old = tmp / "old.html"
            new = tmp / "new.html"
            old.write_text('<div data-ai-id="UI-A">\n  old line\n</div>\n', encoding="utf-8")
            new.write_text('<header>new</header>\n<div data-ai-id="UI-A">\n  changed line\n</div>\n', encoding="utf-8")
            fragment, ok = map_fragment(old, new, "#L1-L3")
            self.assertTrue(ok)
            self.assertEqual(fragment, "#L2-L4")

    def test_consumer_rebind_updates_test_plan_and_xmind(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bundle = self.make_source(tmp)
            source = bundle / ".delivery" / "candidate-revisions" / "r1"
            (source / "需求_测试方案.md").write_text("source revision r1\n", encoding="utf-8")
            xmind = source / "需求_测试用例.xmind"
            with zipfile.ZipFile(xmind, "w") as archive:
                archive.writestr("content.json", json.dumps({"revision": "r1"}))
            manifest_path = tmp / "manifest-consumer.json"
            process = subprocess.run([
                sys.executable, str(TOOL), "--bundle", str(bundle), "--source-revision", "r1",
                "--target-revision", "r2", "--manifest-out", str(manifest_path),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            manifest = json.loads(manifest_path.read_text())
            rebind = {item["path"]: item for item in manifest["consumerRebind"]}
            self.assertIn("需求_测试方案.md", rebind)
            self.assertEqual(rebind["需求_测试方案.md"]["kind"], "TEST_PLAN")
            self.assertIn("需求_测试用例.xmind", rebind)
            self.assertEqual(rebind["需求_测试用例.xmind"]["kind"], "XMind")
            target = bundle / ".delivery" / "candidate-revisions" / "r2"
            self.assertIn("r2", (target / "需求_测试方案.md").read_text())
            with zipfile.ZipFile(target / "需求_测试用例.xmind") as archive:
                self.assertIn("r2", archive.read("content.json").decode())
            schema = json.loads(SCHEMA.read_text())
            self.assertEqual(validate_schema(manifest, schema, schema), [])


if __name__ == "__main__":
    unittest.main()
