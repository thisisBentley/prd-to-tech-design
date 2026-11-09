import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "build_context_pack.py"


class ContextPackTests(unittest.TestCase):
    def test_builds_deterministic_evidence_bound_pack(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "source.json"; out = root / "pack.json"
            source.write_text(json.dumps({
                "facts": [{"id": "FR-1", "text": "Only agents are checked", "sourceRef": "PRD#FR-1"}],
                "evidence": [{"id": "E-1", "ref": "PRD#FR-1", "quote": "only agents"}],
                "rules": ["QA.PERMISSION.001"],
            }), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--pack-type", "ROLE", "--requirement-id", "DEMO-1", "--revision", "r1", "--role", "qa-red-team", "--scope", "FR-1", "--input", source, "--out", out], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["packType"], "ROLE")
            self.assertEqual(data["facts"][0]["id"], "FR-1")
            self.assertEqual(data["evidence"][0]["sha256"], __import__('hashlib').sha256(source.read_bytes()).hexdigest())
            self.assertIn("invent_product_facts", data["forbidden"])


if __name__ == "__main__":
    unittest.main()
