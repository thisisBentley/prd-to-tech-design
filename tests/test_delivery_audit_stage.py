import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
BUNDLE_AUDIT = SCRIPTS / "run_delivery_audit_stage.py"
LOCK = SCRIPTS / "build_policy_lock.py"
FAKE_WORKER = ROOT / "tests" / "fixtures" / "audit" / "fake_audit_worker.py"
PROFILE = ROOT / "config" / "audit-profiles" / "prd-prototype.json"
CROSSWALK = ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeliveryAuditStageTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run(
            [sys.executable, str(executable), *map(str, args)],
            text=True, capture_output=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def sealed_bundle(self, root: Path):
        run_root = root / "run"
        bundle = run_root / "01-delivery"
        dd = bundle / ".delivery"
        frozen = dd / "candidate-revisions" / "r1"
        frozen.mkdir(parents=True)
        (frozen / "artifact.txt").write_text("sealed candidate\n", encoding="utf-8")
        lock = dd / "policy-lock.json"
        self.run_tool(
            LOCK,
            "--artifact-profile", "PRD_PLUS_PROTOTYPE",
            "--requirement-types", "CRUD,UI_INTERACTION",
            "--prototype-status", "TRIGGERED",
            "--ui-ownership", "LOCAL",
            "--out", lock,
        )
        seal = {
            "bundleId": "DEMO",
            "revision": "r1",
            "frozenCopy": ".delivery/candidate-revisions/r1",
            "artifactHashes": {"artifact.txt": sha(frozen / "artifact.txt")},
        }
        (dd / "candidate-seal.json").write_text(json.dumps(seal), encoding="utf-8")
        return run_root, bundle, dd, frozen

    def stage(self, run_root: Path, bundle: Path, expect=0):
        return self.run_tool(
            BUNDLE_AUDIT,
            "--run-root", run_root,
            "--bundle", bundle,
            "--workflow-id", "WF-STAGE",
            "--revision", "r1",
            "--profile", PROFILE,
            "--crosswalk", CROSSWALK,
            "--worker", sys.executable, FAKE_WORKER,
            expect=expect,
        )

    def test_audit_stage_runs_on_candidate_frozen_copy_before_final_seal(self):
        with tempfile.TemporaryDirectory() as td:
            run_root, bundle, dd, frozen = self.sealed_bundle(Path(td))
            result = self.stage(run_root, bundle)
            self.assertEqual(result["status"], "AUDIT_PASS")
            plan = json.loads((dd / "audit-plan.json").read_text())
            self.assertEqual(Path(plan["artifactRoot"]), frozen.resolve())
            self.assertFalse((dd / "final-seal.json").exists())
            stage = json.loads(Path(result["stageReport"]).read_text())
            self.assertEqual(stage["status"], "AUDIT_PASS")
            self.assertTrue(stage["orderChecked"])

    def test_audit_stage_rejects_a_finalized_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            run_root, bundle, dd, _ = self.sealed_bundle(Path(td))
            (dd / "final-seal.json").write_text(json.dumps({"revision": "r1"}), encoding="utf-8")
            result = self.stage(run_root, bundle, expect=1)
            self.assertEqual(result["status"], "AUDIT_ORDER_VIOLATION")

    def test_audit_stage_rejects_candidate_hash_drift(self):
        with tempfile.TemporaryDirectory() as td:
            run_root, bundle, _, frozen = self.sealed_bundle(Path(td))
            (frozen / "artifact.txt").write_text("tampered\n", encoding="utf-8")
            result = self.stage(run_root, bundle, expect=1)
            self.assertEqual(result["status"], "AUDIT_BLOCKED")


if __name__ == "__main__":
    unittest.main()
