import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
RUNNER = ROOT / SCRIPTS / "lane_runner.py"


class LaneRunnerTests(unittest.TestCase):
    def run_runner(self, manifest, workspace, out, workers, expect=0):
        process = subprocess.run([
            sys.executable, str(RUNNER), "--manifest", str(manifest), "--workspace", str(workspace),
            "--out", str(out), "--max-workers", str(workers), "--timeout", "60",
        ], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def make_manifest(self, base, count, missing_last=False):
        lanes = []
        for index in range(count):
            requirement = base / f"req-{index}.md"
            if not (missing_last and index == count - 1):
                requirement.write_text(f"# Requirement {index}\n\nBuild isolated lane {index}.\n", encoding="utf-8")
            lanes.append({
                "laneId": f"REQ-{index}",
                "requirement": str(requirement),
                "requirementName": f"Requirement {index}",
                "artifactProfile": "PRD_ONLY",
            })
        manifest = base / "manifest.json"
        manifest.write_text(json.dumps({"schemaVersion": 1, "lanes": lanes}), encoding="utf-8")
        return manifest

    def test_five_requirements_run_in_isolated_lanes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = self.make_manifest(base, 5)
            workspace = base / "workspaces"
            out = base / "summary.json"
            summary = self.run_runner(manifest, workspace, out, 5)
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["passed"], 5)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(data["lanes"]), 5)
            roots = {lane["runRoot"] for lane in data["lanes"]}
            self.assertEqual(len(roots), 5)
            for lane in data["lanes"]:
                self.assertEqual(lane["status"], "PASS")
                self.assertGreaterEqual(lane["totalDurationSeconds"], 0)
                self.assertTrue((Path(lane["runRoot"]) / ".agents" / "artifacts" / "PRD_DELIVERY.md").exists())
                self.assertTrue((Path(lane["runRoot"]) / ".agents" / "handoffs" / "delivery-ready.handoff.json").exists())

    def test_one_failed_lane_does_not_block_other_lanes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = self.make_manifest(base, 3, missing_last=True)
            workspace = base / "workspaces"
            out = base / "summary.json"
            summary = self.run_runner(manifest, workspace, out, 3, expect=1)
            self.assertEqual(summary["status"], "PARTIAL")
            self.assertEqual(summary["passed"], 2)
            self.assertEqual(summary["failed"], 1)
            data = json.loads(out.read_text(encoding="utf-8"))
            failed = next(lane for lane in data["lanes"] if lane["laneId"] == "REQ-2")
            passed = [lane for lane in data["lanes"] if lane["status"] == "PASS"]
            self.assertEqual(failed["status"], "FAIL")
            self.assertEqual(len(passed), 2)
            for lane in passed:
                self.assertTrue((Path(lane["runRoot"]) / ".agents" / "handoffs" / "delivery-ready.handoff.json").exists())


if __name__ == "__main__":
    unittest.main()
