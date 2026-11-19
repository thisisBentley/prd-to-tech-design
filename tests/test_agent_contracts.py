import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
sys.path.insert(0, str(TOOLS))

from agent_contracts import normalize_result, validate_agent_result, validate_schema_value  # noqa: E402

BUILD = TOOLS / "build_agent_contract.py"
VALIDATE = TOOLS / "validate_agent_result.py"
COMPILE = TOOLS / "compile_training_record.py"
AUDIT = TOOLS / "audit_dataset_contract.py"


def run(argv, stdin=None):
    return subprocess.run(argv, input=stdin, text=True, capture_output=True)


def contract_profile():
    return {
        "schemaVersion": 1,
        "releaseId": "TEST-RELEASE",
        "releaseVersion": "1.0.0",
        "status": "PUBLISHED",
        "contracts": [{
            "schemaVersion": 1,
            "contractId": "AGENT-REVIEW-V1",
            "contractVersion": "1.0.0",
            "taskType": "REVIEW",
            "capabilityMode": "REVIEW",
            "outputSchemaRef": "agent-result.schema.json",
            "allowedTaskStatus": ["COMPLETED", "BLOCKED", "UNKNOWN"],
            "allowedVerdicts": ["PASS", "FINDINGS", "NOT_APPLICABLE"],
            "requiredSections": ["evidence", "conclusions", "findings", "unknowns", "boundary"],
            "evidencePolicy": {"mustCite": True, "minEvidenceRefs": 1, "allowedRefsFrom": "contextPack"},
            "gradingRubricRef": "delivery-quality-benchmark.schema.json",
            "constraints": ["Use only frozen task inputs."],
            "createdAt": "2026-11-19T00:00:00+08:00"
        }]
    }


class AgentContractTests(unittest.TestCase):
    def test_build_release_and_validate_contract_schema(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = root / "profile.json"
            out = root / "release.json"
            profile.write_text(json.dumps(contract_profile()), encoding="utf-8")
            proc = run([sys.executable, str(BUILD), "--profile", str(profile), "--out", str(out), "--generated-at", "2026-11-19T00:00:00+08:00"])
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            release = json.loads(out.read_text())
            self.assertEqual(release["releaseId"], "TEST-RELEASE")
            self.assertIn("AGENT-REVIEW-V1", release["contractHashes"])
            self.assertEqual(validate_schema_value(release, "agent-contract-release.schema.json"), [])

    def test_normalization_fails_closed_and_plans_repair(self):
        contract = contract_profile()["contracts"][0]
        review = normalize_result({"reviewVerdict": "FINDINGS", "conclusions": ["Review completed."], "evidence": [{"ref": "a.md"}], "unknowns": []}, contract, "T1", ["a.md"])
        self.assertEqual(review["taskStatus"], "UNKNOWN")
        self.assertEqual(review["reviewVerdict"], "NOT_APPLICABLE")
        self.assertTrue(review["unknowns"])
        repair_contract = dict(contract)
        repair_contract["contractId"] = "AGENT-REPAIR-V1"
        repair_contract["allowedVerdicts"] = ["REPAIR_PLAN"]
        repair = normalize_result({"reviewVerdict": "REPAIR_PLAN", "conclusions": ["Fix the binding."], "findings": [{"title": "Bad binding", "evidenceRefs": ["a.md"]}], "evidence": [{"ref": "a.md"}]}, repair_contract, "T2", ["a.md"])
        self.assertEqual(repair["taskStatus"], "COMPLETED")
        self.assertEqual(repair["reviewVerdict"], "REPAIR_PLAN")
        self.assertEqual(len(repair["findings"]), 1)

    def test_validator_rejects_evidence_outside_context_pack(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = root / "profile.json"
            release_path = root / "release.json"
            result_path = root / "result.json"
            context_path = root / "context.json"
            profile.write_text(json.dumps(contract_profile()), encoding="utf-8")
            self.assertEqual(run([sys.executable, str(BUILD), "--profile", str(profile), "--out", str(release_path)]).returncode, 0)
            contract = json.loads(release_path.read_text())["contracts"][0]
            result = {
                "schemaVersion": 1, "contractId": contract["contractId"], "contractVersion": contract["contractVersion"],
                "taskId": "T1", "taskStatus": "COMPLETED", "decisionType": "REVIEW", "reviewVerdict": "PASS", "evidence": [{"ref": "other.md", "claim": "claim"}],
                "conclusions": ["Supported."], "findings": [], "unknowns": [], "boundary": ["frozen inputs"]
            }
            context = {"schemaVersion": 1, "packId": "p", "packType": "ROLE", "requirementId": "R", "revision": "r1", "sourceArtifacts": [{"path": "a.md", "sha256": "0" * 64}], "facts": [], "evidence": [{"id": "E1", "ref": "a.md", "sha256": "0" * 64}], "rules": [], "forbidden": [], "createdAt": "2026-11-19T00:00:00+08:00"}
            result_path.write_text(json.dumps(result), encoding="utf-8")
            context_path.write_text(json.dumps(context), encoding="utf-8")
            proc = run([sys.executable, str(VALIDATE), "--release", str(release_path), "--result", str(result_path), "--context-pack", str(context_path), "--json"])
            self.assertEqual(proc.returncode, 1)
            report = json.loads(proc.stdout)
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any("EVIDENCE_ALLOWED" in error for error in report["errors"]))

    def test_compile_and_audit_training_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dataset = root / "dataset"
            sample = dataset / "issues" / "DEMO-1"
            (sample / "00-source" / "jira" / "artifacts").mkdir(parents=True)
            (sample / "00-source" / "jira" / "artifacts" / "prd.md").write_text("# PRD\n", encoding="utf-8")
            profile = root / "profile.json"
            release = root / "release.json"
            profile.write_text(json.dumps(contract_profile()), encoding="utf-8")
            self.assertEqual(run([sys.executable, str(BUILD), "--profile", str(profile), "--out", str(release)]).returncode, 0)
            user = {
                "taskId": "TASK-DEMO", "sampleId": "DEMO-1", "capabilityMode": "REVIEW", "taskType": "REVIEW",
                "evidencePack": {"allowedArtifacts": [{"ref": "jira/artifacts/prd.md"}]},
                "outputContract": {"taskStatus": "COMPLETED | BLOCKED | UNKNOWN", "reviewVerdict": "PASS | FINDINGS | NOT_APPLICABLE", "requiredSections": ["evidence"], "mustCiteEvidence": True}
            }
            source = {
                "schemaVersion": 1, "recordId": "REC-DEMO", "taskId": "TASK-DEMO", "sampleId": "DEMO-1",
                "capabilityMode": "REVIEW", "taskType": "REVIEW", "evidencePack": user["evidencePack"],
                "messages": [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                    {"role": "assistant", "content": "{}"}
                ],
                "referenceAnswer": {"reviewVerdict": "FINDINGS", "conclusions": ["Needs more evidence."], "evidence": [{"ref": "jira/artifacts/prd.md"}], "findings": [{"title": "Missing detail", "evidenceRefs": ["jira/artifacts/prd.md"]}], "unknowns": []},
                "approval": {"trainingApproved": False}
            }
            source_path = root / "source.jsonl"
            source_path.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")
            compiled_path = root / "compiled.jsonl"
            contexts = root / "contexts"
            proc = run([sys.executable, str(COMPILE), "--input", str(source_path), "--release", str(release), "--out", str(compiled_path), "--context-dir", str(contexts), "--dataset-root", str(dataset), "--strict"])
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            compiled = json.loads(compiled_path.read_text().splitlines()[0])
            self.assertEqual(compiled["contractValidation"]["status"], "PASS")
            payload = json.loads(compiled["messages"][1]["content"])
            self.assertEqual(payload["outputContract"]["contractId"], "AGENT-REVIEW-V1")
            audit_path = root / "audit.json"
            proc = run([sys.executable, str(AUDIT), "--input", str(compiled_path), "--release", str(release), "--dataset-root", str(dataset), "--out", str(audit_path), "--strict"])
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            audit = json.loads(audit_path.read_text())
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["passed"], 1)


if __name__ == "__main__":
    unittest.main()
