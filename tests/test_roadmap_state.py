import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILD = TOOLS / "build_roadmap_state.py"
VALIDATE = TOOLS / "validate_roadmap_state.py"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class RoadmapStateTests(unittest.TestCase):
    def sources(self, root, iteration=73, milestone="M7.5-D1"):
        roadmap = root / "roadmap.md"
        changelog = root / "changelog.md"
        manifest = root / "manifest.json"
        dataset = root / "dataset.json"
        roadmap.write_text(f"- 当前迭代：{iteration}\n- 当前主线：**{milestone} 语义收敛底座**\n", encoding="utf-8")
        changelog.write_text(f"- 当前迭代：{iteration}\n", encoding="utf-8")
        manifest.write_text(json.dumps({"baselineId": "B-1", "localSkill": {"version": "0.18.0"}, "currentMilestone": {"id": milestone}}), encoding="utf-8")
        dataset.write_text(json.dumps({"latestMilestone": {"id": milestone}, "trainingRemediation": {"baselineStatus": "B2_PARTIAL"}}), encoding="utf-8")
        return roadmap, changelog, manifest, dataset

    def args(self, paths, snapshot, expected="M7.5-D1", strict=False):
        roadmap, changelog, manifest, dataset = paths
        values = ["--roadmap", roadmap, "--changelog", changelog, "--version-manifest", manifest, "--dataset-status", dataset, "--expected-milestone", expected]
        if snapshot:
            values.extend(["--snapshot", snapshot])
        return values

    def test_snapshot_passes_and_validation_detects_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.sources(root)
            snapshot = root / "state.json"
            built = run([BUILD, *self.args(paths, None), "--out", snapshot, "--strict"])
            self.assertEqual(built["status"], "PASS")
            valid = run([VALIDATE, *self.args(paths, snapshot)])
            self.assertEqual(valid["status"], "PASS")
            paths[0].write_text("- 当前迭代：74\n- 当前主线：**M7.5-D1 语义收敛底座**\n", encoding="utf-8")
            failed = run([VALIDATE, *self.args(paths, snapshot)], expect=1)
            self.assertEqual(failed["status"], "FAIL")
            self.assertTrue(any("source drift" in error for error in failed["errors"]))

    def test_milestone_mismatch_fails_strict_build(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self.sources(root, milestone="M7.5-C")
            result = run([BUILD, *self.args(paths, None), "--out", root / "state.json", "--strict"], expect=1)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("STATE.MILESTONE" in item for item in result["drift"]))


if __name__ == "__main__":
    unittest.main()
