import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "classify_change.py"


class ChangeClassificationTests(unittest.TestCase):
    def classify(self, old_files, new_files):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); old = root / "r1"; new = root / "r2"; out = root / "result.json"
            for base, data in [(old, old_files), (new, new_files)]:
                base.mkdir()
                for name, text in data.items():
                    path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--previous", old, "--current", new, "--previous-revision", "r1", "--current-revision", "r2", "--out", out], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(out.read_text())

    def test_evidence_only_does_not_require_core_review(self):
        result = self.classify({"Demo_PRD_DELIVERY.md": "same", "Demo_Gates.md": "r1"}, {"Demo_PRD_DELIVERY.md": "same", "Demo_Gates.md": "r2"})
        self.assertEqual(result["classification"], "EVIDENCE_ONLY")
        self.assertEqual(result["recommendedAction"], "DETERMINISTIC_EVIDENCE_RECHECK")
        self.assertFalse(result["coreChanged"])

    def test_projection_only_requires_projection_review(self):
        result = self.classify({"Demo_PRD_DELIVERY.md": "same", "Demo_Overview.html": "r1"}, {"Demo_PRD_DELIVERY.md": "same", "Demo_Overview.html": "r2"})
        self.assertEqual(result["classification"], "PROJECTION")
        self.assertEqual(result["recommendedAction"], "PROJECTION_REVIEW")

    def test_semantic_change_requires_full_core_review(self):
        result = self.classify({"Demo_PRD_DELIVERY.md": "r1"}, {"Demo_PRD_DELIVERY.md": "r2"})
        self.assertEqual(result["classification"], "SEMANTIC")
        self.assertEqual(result["recommendedAction"], "FULL_CORE_REVIEW")
        self.assertTrue(result["coreChanged"])

    def test_unknown_change_fails_safe_to_manual_triage(self):
        result = self.classify({"custom.bin": "r1"}, {"custom.bin": "r2"})
        self.assertEqual(result["classification"], "UNKNOWN")
        self.assertEqual(result["recommendedAction"], "MANUAL_TRIAGE")
        self.assertTrue(result["coreChanged"])


if __name__ == "__main__":
    unittest.main()
