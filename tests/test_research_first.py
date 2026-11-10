import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "validate_research_first.py"

class ResearchFirstTests(unittest.TestCase):
    def run_tool(self, *args, expect=0):
        proc = subprocess.run([sys.executable, str(TOOL), *map(str,args)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)
    def record(self, verdict, decision_required):
        return {"schemaVersion":1,"researchId":"R-1","workflowId":"WF-1","clue":"回答类型字段映射","clueType":"FIELD_MAPPING","researchPlan":[{"source":"JIRA","query":"回答类型 字段映射","purpose":"查历史实现"}],"sourcesChecked":[{"source":"JIRA","status":"AVAILABLE","evidenceRefs":["jira://BOT-1"]}],"findings":[{"claim":"历史需求已固定使用现有字段","evidenceRefs":["jira://BOT-1"],"confidence":"HIGH"}],"verdict":verdict,"decisionRequired":decision_required,"evidenceRefs":["jira://BOT-1"],"createdAt":"2026-11-10T00:00:00Z"}
    def test_fact_resolved_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=root/"r.json"; p.write_text(json.dumps(self.record("FACT_RESOLVED", False)))
            self.run_tool("--research",p,"--out",root/"out.json")
    def test_needs_business_decision_requires_rationale(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=root/"r.json"; d=self.record("NEEDS_BUSINESS_DECISION", True); p.write_text(json.dumps(d))
            self.run_tool("--research",p,"--out",root/"out.json",expect=1)
    def test_technical_no_evidence_does_not_require_product_decision(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); record=self.record("NO_EVIDENCE", False)
            record.update({"resolutionOwner":"TECH","decisionRationale":"Interface contract is absent; technical research must resolve it before design.","nextAction":"Request the DialogOS interface contract from engineering."})
            path=root/"r.json"; path.write_text(json.dumps(record))
            self.run_tool("--research",path,"--out",root/"out.json")
    def test_non_product_no_evidence_requires_non_product_owner(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); record=self.record("NO_EVIDENCE", False)
            record.update({"resolutionOwner":"PRODUCT","decisionRationale":"Missing implementation evidence."})
            path=root/"r.json"; path.write_text(json.dumps(record))
            self.run_tool("--research",path,"--out",root/"out.json",expect=1)
    def test_decision_card_requires_research_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); p=root/"d.json"; p.write_text(json.dumps({"schemaVersion":1,"decisionId":"D","workflowId":"WF","businessScenario":"x","currentFacts":["x"],"ambiguity":"x","options":[{"optionId":"A"},{"optionId":"B"}],"recommendation":"A","defaultAndRisk":"x","owner":"p","closeCondition":"x","researchRecordPath":"r.json","researchVerdict":"FACT_RESOLVED","researchEvidenceRefs":["jira://1"],"whyDecisionRequired":"x","createdAt":"2026-11-10T00:00:00Z"}))
            self.run_tool("--decision",p,"--out",root/"out.json",expect=1)

class QualityExitResearchTests(unittest.TestCase):
    def run_tool(self, *args, expect=0):
        proc = subprocess.run([sys.executable, str(ROOT / SCRIPTS / "delivery_quality_exit.py"), *map(str,args)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)
    def prepare(self, root, card):
        (root/'.agents'/'reviews').mkdir(parents=True)
        (root/'.agents'/'decisions').mkdir(parents=True)
        (root/'.agents'/'research').mkdir(parents=True)
        decision_result=root/'decision.json'; decision_result.write_text(json.dumps({"readiness":"READY","decision":"PROCEED"}))
        plan=root/'plan.json'; plan.write_text(json.dumps({"tasks":[{"taskId":"DECISION-READINESS","status":"SUCCEEDED","resultPath":str(decision_result)}]}))
        (root/'.agents'/'reviews'/'review.json').write_text(json.dumps({"verdict":"ACCEPTED","blockingCount":0}))
        (root/'.agents'/'decisions'/'d.json').write_text(json.dumps(card))
        return plan
    def test_quality_exit_blocks_open_decision_without_research(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); card={"schemaVersion":1,"decisionId":"D-1","workflowId":"WF-1","reviewerRole":"delivery-reviewer","businessScenario":"x","currentFacts":["x"],"ambiguity":"x","options":[{"optionId":"A","label":"A","result":"A","impact":"A","reversibility":"reversible"},{"optionId":"B","label":"B","result":"B","impact":"B","reversibility":"reversible"}],"recommendation":"A","defaultAndRisk":"x","owner":"product","closeCondition":"x","researchRecordPath":"missing.json","researchVerdict":"NEEDS_BUSINESS_DECISION","researchEvidenceRefs":["jira://1"],"whyDecisionRequired":"x","status":"open","createdAt":"2026-11-10T00:00:00Z"}
            plan=self.prepare(root,card)
            result=self.run_tool("--run-root",root,"--plan",plan,"--out",root/'out.json',expect=1)
            self.assertEqual(result['status'],'BLOCKED')
            data=json.loads((root/'out.json').read_text()); self.assertTrue(any(c['checkId']=='QUALITY.DECISIONS' and c['status']=='failed' for c in data['checks']))
if __name__=="__main__": unittest.main()
