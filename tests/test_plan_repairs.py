import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPTS="scripts" if ROOT.name=="ai-native-delivery" else "tools"; TOOL=ROOT/SCRIPTS/"plan_repairs.py"
class PlanRepairTests(unittest.TestCase):
 def test_builds_tasks_by_repair_class(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); batch=root/"batch.json"; out=root/"plan.json"
   batch.write_text(json.dumps({"status":"READY_FOR_REPAIR","workflowId":"WF-1","targetRevision":"r2","groups":[{"rootCauseId":"VISIBLE-001","repairClass":"VISIBLE_INTERACTION","ruleIds":["U1.ACTION_FEEDBACK"],"closeConditions":["label visible"],"regressionTests":["visible check"]}]}),encoding="utf-8")
   p=subprocess.run([sys.executable,str(TOOL),"--batch",batch,"--out",out],text=True,capture_output=True); self.assertEqual(p.returncode,0,p.stderr)
   d=json.loads(out.read_text()); self.assertEqual(d["status"],"READY"); self.assertEqual(d["tasks"][0]["role"],"prototype-repair-agent"); self.assertEqual(d["tasks"][0]["rootCauseId"],"VISIBLE-001"); self.assertEqual(d["tasks"][0]["ruleIds"],["U1.ACTION_FEEDBACK"])
if __name__=="__main__": unittest.main()
