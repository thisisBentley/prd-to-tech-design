import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("provenance", ROOT / "tools" / "validate_source_provenance.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ProvenanceTests(unittest.TestCase):
    def test_detects_prototype_prd_version_drift(self):
        mod = load()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / ".delivery").mkdir()
            (root / ".delivery/ui-pack.lock.json").write_text(json.dumps({"packHash":"a"*64,"standardsHash":"b"*64,"resourceIndexHash":"c"*64,"u1Gate":{"version":"1.3"},"u2Gate":{"version":"1.1"}}))
            prd = root / "prd.md"; prd.write_text("当前版本: v1.1")
            proto = root / "proto.html"; proto.write_text('<meta name="source-prd-version" content="v1.23">')
            errors = mod.validate(root, prd, proto, None, None)
            self.assertTrue(any("prototype declares v1.23" in e for e in errors))

    def test_passes_matching_versions(self):
        mod = load()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / ".delivery").mkdir()
            (root / ".delivery/ui-pack.lock.json").write_text(json.dumps({"packHash":"a"*64,"standardsHash":"b"*64,"resourceIndexHash":"c"*64,"u1Gate":{"version":"1.3"},"u2Gate":{"version":"1.1"}}))
            prd = root / "prd.md"; prd.write_text("当前版本: v1.1")
            proto = root / "proto.html"; proto.write_text('<meta name="source-prd-version" content="v1.1">')
            self.assertEqual(mod.validate(root, prd, proto, None, None), [])


if __name__ == "__main__":
    unittest.main()
