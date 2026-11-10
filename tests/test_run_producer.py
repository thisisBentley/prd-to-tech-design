import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "run_producer.py"


class RunProducerTests(unittest.TestCase):
    def fake(self, root, fail=False):
        path = root / "producer.py"
        path.write_text(f'''import json,os,sys
from pathlib import Path
request=json.load(sys.stdin)
out=Path(request["outputDir"])
(out/"Prototype.html").write_text("<!doctype html><html><body>produced</body></html>",encoding="utf-8")
(out/"prototype-manifest.json").write_text(json.dumps({{"elements":[{{"uiElementId":"x"}}]}}),encoding="utf-8")
sys.exit(1 if {fail!r} else 0)
''', encoding="utf-8")
        return path

    def run_producer(self, root, fail=False, expect=0):
        producer = self.fake(root, fail)
        registry = root / "registry.json"
        registry.write_text(json.dumps({"schemaVersion": 1, "producers": [{"kind": "prototype", "mode": "semantic", "command": [sys.executable, str(producer)], "requiredArtifacts": ["Prototype.html", "prototype-manifest.json"]}]}), encoding="utf-8")
        out = root / "result.json"
        proc = subprocess.run([sys.executable, str(TOOL), "--registry", str(registry), "--kind", "prototype", "--workflow-id", "WF", "--run-root", root, "--output-dir", str(root / "out"), "--out", str(out)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(out.read_text())

    def test_producer_outputs_are_verified_and_hashed(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_producer(Path(td))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["mode"], "semantic")
            self.assertEqual(len(result["artifacts"]), 2)
            self.assertEqual(len(result["artifacts"][0]["sha256"]), 64)

    def test_missing_required_artifact_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            producer = root / "producer.py"
            producer.write_text('import json,sys\\njson.load(sys.stdin)\\nprint("ok")\\n', encoding="utf-8")
            registry = root / "registry.json"
            registry.write_text(json.dumps({"schemaVersion": 1, "producers": [{"kind": "prototype", "mode": "semantic", "command": [sys.executable, str(producer)], "requiredArtifacts": ["Prototype.html"]}]}), encoding="utf-8")
            out = root / "result.json"
            proc = subprocess.run([sys.executable, str(TOOL), "--registry", str(registry), "--kind", "prototype", "--workflow-id", "WF", "--run-root", root, "--output-dir", str(root / "out"), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(json.loads(out.read_text())["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
