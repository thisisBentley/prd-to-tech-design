import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILD = TOOLS / "build_source_pack.py"
VALIDATE = TOOLS / "validate_source_pack.py"
ROUTE = TOOLS / "route_specialist_tool.py"
CURRENT_PACK = ROOT / "config" / "source-packs" / "current-v1.json"
ROUTE_POLICY = ROOT / "config" / "trust-kernel" / "specialist-tool-routes-v1.json"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class SourcePackRegistryTests(unittest.TestCase):
    def source(self, source_id, source_class, authority, uses, path, locator="REPO_PATH", **overrides):
        data = {
            "sourceId": source_id,
            "sourceClass": source_class,
            "authorityLevel": authority,
            "allowedUses": uses,
            "owner": "test-owner",
            "domain": "PRODUCT_ENGINEERING",
            "locatorType": locator,
            "pathOrRef": path,
            "sha256": None,
            "sourceLock": {"kind": "CONTENT_HASH", "locator": path, "status": "LOCKED"},
            "freshness": {"status": "FRESH", "observedAt": "2026-11-23T00:00:00+00:00"},
            "license": {"status": "KNOWN", "expression": "PROPRIETARY"},
            "confidentiality": "INTERNAL",
            "trainingCandidate": False,
        }
        data.update(overrides)
        return data

    def catalog(self, root):
        files = {}
        for key in ("normative", "fact", "measured", "derived"):
            path = root / f"{key}.json"
            path.write_text(json.dumps({"kind": key}), encoding="utf-8")
            files[key] = path.name
        sources = [
            self.source("SP-USER-DECISION", "NORMATIVE", "USER_DECISION", ["DESIGN_REFERENCE", "RUNTIME_INPUT"], files["normative"]),
            self.source("SP-SOURCE-FACT", "SOURCE_FACT", "SOURCE_FACT", ["DESIGN_REFERENCE", "EVALUATION_CORPUS", "RUNTIME_INPUT"], files["fact"]),
            self.source("SP-MEASURED", "MEASURED", "MEASURED", ["DESIGN_REFERENCE", "EVALUATION_CORPUS", "RUNTIME_INPUT"], files["measured"]),
            self.source("SP-DERIVED", "DERIVED", "DERIVED", ["DESIGN_REFERENCE", "EVALUATION_CORPUS", "RUNTIME_INPUT"], files["derived"]),
            self.source(
                "SP-REFERENCE", "REFERENCE", "REFERENCE", ["DESIGN_REFERENCE"],
                "attachment://reference.pdf", locator="ATTACHMENT", sha256="a" * 64,
                sourceLock={"kind": "CONTENT_HASH", "locator": "attachment://reference.pdf", "status": "LOCKED"},
                license={"status": "UNKNOWN", "expression": None},
            ),
            self.source(
                "SP-INFERENCE", "INFERENCE", "INFERENCE", ["DESIGN_REFERENCE"],
                "conversation://inference", locator="CONVERSATION", sha256=None,
                sourceLock={"kind": "TRANSCRIPT", "locator": "conversation://inference", "status": "LOCKED"},
            ),
        ]
        data = {"schemaVersion": 1, "packId": "TEST-PACK", "sources": sources, "conflicts": []}
        path = root / "catalog.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_build_and_validate_all_source_classes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self.catalog(root)
            out = root / "registry.json"
            result = run([BUILD, "--catalog", catalog, "--repo-root", root, "--out", out])
            self.assertEqual(result["status"], "PASS")
            registry = json.loads(out.read_text())
            self.assertEqual(registry["metrics"]["sourceCount"], 6)
            self.assertEqual(registry["coverage"]["REFERENCE"]["status"], "PRESENT")
            self.assertEqual(registry["coverage"]["INFERENCE"]["status"], "PRESENT")
            validated = run([VALIDATE, "--registry", out, "--repo-root", root])
            self.assertEqual(validated["status"], "PASS")

    def test_reference_cannot_be_training_or_runtime_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog_path = self.catalog(root)
            catalog = json.loads(catalog_path.read_text())
            reference = next(item for item in catalog["sources"] if item["sourceClass"] == "REFERENCE")
            reference["allowedUses"] = ["EVALUATION_CORPUS"]
            reference["trainingCandidate"] = True
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            result = run([BUILD, "--catalog", catalog_path, "--repo-root", root, "--out", root / "registry.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("REFERENCE sources may only be used as DESIGN_REFERENCE", result["error"])

    def test_hash_drift_is_detected_after_build(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self.catalog(root)
            out = root / "registry.json"
            run([BUILD, "--catalog", catalog, "--repo-root", root, "--out", out])
            (root / "fact.json").write_text('{"kind":"changed"}', encoding="utf-8")
            result = run([VALIDATE, "--registry", out, "--repo-root", root], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("sha256 drift" in error for error in result["errors"]))

    def test_current_pack_is_valid_and_has_no_training_candidates(self):
        result = run([VALIDATE, "--registry", CURRENT_PACK, "--repo-root", ROOT])
        self.assertEqual(result["status"], "PASS")
        registry = json.loads(CURRENT_PACK.read_text())
        self.assertEqual(registry["metrics"]["trainingCandidateCount"], 0)
        self.assertEqual(registry["coverage"]["INFERENCE"]["status"], "NOT_PRESENT")

    def test_cross_domain_tool_route_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            policy = {
                "schemaVersion": 1,
                "policyId": "CROSS-DOMAIN-TEST",
                "routes": [{
                    "routeId": "FINANCE-TOOL",
                    "executionModes": ["TARGETED_REVISION"],
                    "intents": ["PRD_LOCAL_REVISION"],
                    "tool": {
                        "toolId": "vibe-trading-reader",
                        "kind": "READ_ONLY_DIAGNOSIS",
                        "entrypoint": "vibe-trading",
                        "allowedWriteScope": [],
                        "externalGateRequired": False,
                        "toolDomain": "FINANCE_MARKET_RESEARCH",
                        "allowedTaskDomains": ["FINANCE_MARKET_RESEARCH"],
                        "allowedOperations": ["SELECT", "READ"],
                    },
                }],
            }
            policy_path = root / "routes.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            out = root / "route.json"
            result = run([
                ROUTE, "--workflow-id", "WF-X", "--execution-mode", "TARGETED_REVISION",
                "--intent", "PRD_LOCAL_REVISION", "--policy", policy_path,
                "--task-domain", "PRODUCT_ENGINEERING", "--out", out,
            ], expect=1)
            self.assertEqual(result["status"], "ESCALATE")
            route = json.loads(out.read_text())
            self.assertEqual(route["applicability"]["status"], "BLOCKED")
            self.assertIn("task domain PRODUCT_ENGINEERING is not allowed", route["reason"])

    def test_source_pack_binding_rejects_unknown_ref(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = self.catalog(root)
            pack = root / "registry.json"
            run([BUILD, "--catalog", catalog, "--repo-root", root, "--out", pack])
            policy = json.loads(ROUTE_POLICY.read_text())
            policy["routes"][0]["tool"]["sourcePackRefs"] = ["SP-DOES-NOT-EXIST"]
            policy_path = root / "routes.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            out = root / "route.json"
            result = run([
                ROUTE, "--workflow-id", "WF-X", "--execution-mode", "TARGETED_REVISION",
                "--intent", "PRD_LOCAL_REVISION", "--policy", policy_path,
                "--source-pack", pack, "--out", out,
            ], expect=1)
            self.assertEqual(result["status"], "ESCALATE")
            route = json.loads(out.read_text())
            self.assertEqual(route["applicability"]["sourcePackStatus"], "BLOCKED")
            self.assertIn("unknown sourcePackRef", route["reason"])


if __name__ == "__main__":
    unittest.main()
