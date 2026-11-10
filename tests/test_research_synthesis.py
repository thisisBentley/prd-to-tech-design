import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
SYNTH = ROOT / SCRIPTS / "synthesize_research.py"
CLOSE = ROOT / SCRIPTS / "close_decision.py"


class ResearchSynthesisTests(unittest.TestCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def request(self):
        return {
            "schemaVersion": 1, "workflowId": "WF-SYNTH", "requirementKey": "DEMO-1",
            "clues": [
                {"clueId": "C-FACT", "clue": "existing field mapping", "clueType": "FIELD_MAPPING", "queries": [{"queryId": "Q-1", "source": "JIRA", "query": "field", "purpose": "verify"}]},
                {"clueId": "C-DECISION", "clue": "what users see when a metric is undefined", "clueType": "BUSINESS_POLICY", "resolutionOwner": "PRODUCT", "decisionQuestion": "Use blank or 0.00%?", "decisionOptions": [{"optionId": "A", "label": "Blank", "result": "blank", "impact": "no false signal", "reversibility": "reversible"}, {"optionId": "B", "label": "0.00%", "result": "zero", "impact": "template-compatible", "reversibility": "reversible"}], "queries": [{"queryId": "Q-2", "source": "JIRA", "query": "metric", "purpose": "verify"}]},
            ],
        }

    def query_result(self):
        return {
            "schemaVersion": 1, "workflowId": "WF-SYNTH", "status": "COMPLETE", "requestSha256": "a" * 64,
            "records": [
                {"clueId": "C-FACT", "source": "JIRA", "queryId": "Q-1", "query": "field", "status": "CONFIRMED", "sourceRef": "jira://DEMO-1", "claims": [{"claim": "field exists", "confidence": "HIGH", "field": "mapping"}], "evidenceRefs": ["jira://DEMO-1#field"], "attempts": []},
                {"clueId": "C-DECISION", "source": "JIRA", "queryId": "Q-2", "query": "metric", "status": "UNAVAILABLE", "claims": [], "evidenceRefs": [], "attempts": [], "error": "not found"},
            ],
            "metrics": {"queries": 2, "available": 1, "errors": 1, "retries": 0}, "generatedAt": "2026-11-10T00:00:00Z",
        }

    def test_synthesis_creates_fact_record_technical_gap_and_decision_card(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = root / "request.json"; self.write(request, self.request())
            query = root / "query.json"; self.write(query, self.query_result())
            run = root / "run"; out = root / "summary.json"
            proc = subprocess.run([sys.executable, str(SYNTH), "--request", str(request), "--query-result", str(query), "--run-root", str(run), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            summary = json.loads(out.read_text())
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["researchRecords"], 2)
            self.assertEqual(summary["decisionCards"], 1)
            index = json.loads((run / ".agents" / "research" / "index.json").read_text())
            self.assertEqual(len(index["records"]), 2)
            open_card = list((run / ".agents" / "decisions").glob("*.json"))[0]
            card = json.loads(open_card.read_text())
            self.assertEqual(card["status"], "open")
            self.assertEqual(card["researchVerdict"], "NEEDS_BUSINESS_DECISION")
            gaps = json.loads((run / ".agents" / "context" / "technical-gaps.json").read_text())
            self.assertEqual(gaps["gaps"], [])

    def test_close_decision_emits_resync_instruction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = root / "request.json"; self.write(request, self.request())
            query = root / "query.json"; self.write(query, self.query_result())
            run = root / "run"
            subprocess.run([sys.executable, str(SYNTH), "--request", str(request), "--query-result", str(query), "--run-root", str(run)], check=True, capture_output=True)
            card_path = list((run / ".agents" / "decisions").glob("*.json"))[0]
            out = root / "closed.json"; resync = root / "resync.json"
            proc = subprocess.run([sys.executable, str(CLOSE), "--decision", str(card_path), "--selected-option", "A", "--closed-by", "product-owner", "--out", str(out), "--resync-out", str(resync)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            card = json.loads(out.read_text())
            self.assertEqual(card["status"], "confirmed")
            self.assertEqual(card["selectedOptionId"], "A")
            instruction = json.loads(resync.read_text())
            self.assertTrue(instruction["requiresPrdResync"])


if __name__ == "__main__":
    unittest.main()
