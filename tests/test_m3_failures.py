import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
ORCH = ROOT / SCRIPTS / "orchestrate.py"
LOOP = ROOT / SCRIPTS / "delivery_loop.py"


WORKER = r'''
import hashlib, json, os
from pathlib import Path

def load(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def save(path, data):
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
task=load(os.environ["AI_NATIVE_TASK_MANIFEST"]); tid=task["taskId"]; role=task["role"]; root=Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve(); result_path=Path(os.environ["AI_NATIVE_RESULT_PATH"]); review_path=Path(os.environ["AI_NATIVE_REVIEW_PATH"]); artifact_path=Path(os.environ["AI_NATIVE_ARTIFACT_PATH"]); mode=os.environ.get("M3_MODE","repeat")
context=os.environ.get("AI_NATIVE_CONTEXT_ID","ctx")
paths=[str(root/Path(x["path"])) if not Path(x["path"]).is_absolute() else x["path"] for x in task.get("inputs",[])]

def accepted_review(extra_findings=None):
    findings=extra_findings or []
    return {"schemaVersion":1,"reviewRunId":"R-"+tid,"reviewPlanId":"P-"+tid,"workflowId":task["workflowId"],"producerRole":"prd-producer","reviewerRole":role,"reviewType":"independent","targetHandoffId":"H-"+tid,"targetRevision":"r1","independentContext":True,"verdict":"ACCEPTED" if not findings else "RETURNED","completionStatus":"complete","checks":[{"checkId":"C-1","status":"passed" if not findings else "failed","evidenceRefs":paths or ["prd"],"observed":"reviewed","expected":"sound"}],"findings":findings,"blockingCount":len(findings),"evidenceRefs":paths or ["prd"],"reviewerContextId":context,"reviewerTranscript":str(Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"]).resolve()),"checkedAt":"2026-11-10T00:00:00Z"}

def finding(root,title):
    return {"findingId":"F-"+root,"severity":"BLOCKING","title":title,"evidenceRefs":paths or ["prd"],"impact":"quality gap","closeCondition":"fix gap","owner":"prd-repair-agent","rootCauseId":root,"repairClass":"SEMANTIC","expectedInvariant":"the reviewed fact is present","regressionTests":["rerun review"]}

if tid == "DECISION-READINESS":
    payload={"schemaVersion":1,"status":"SUCCEEDED","taskId":tid,"role":role,"outputs":[{"path":"decision-context","kind":"decision-context"}],"readiness":"READY","decision":"PROCEED","blockingConditions":[],"requiredDecisions":[],"researchRecords":[],"resolvedFacts":[],"evidenceRefs":paths}
elif tid == "PRD-PRODUCE" or tid.startswith("PRD-REPAIR-"):
    artifact_path.parent.mkdir(parents=True, exist_ok=True); artifact_path.write_text("# PRD\n\n- FR-001: Requirement\n- AC-001: Requirement works\n",encoding="utf-8")
    payload={"schemaVersion":1,"status":"SUCCEEDED","taskId":tid,"role":role,"outputs":[{"path":"PRD_DELIVERY.md","kind":"PRD"}],"prdArtifactPath":str(artifact_path),"prdArtifactSha256":hashlib.sha256(artifact_path.read_bytes()).hexdigest(),"evidenceRefs":paths}
elif role in {"delivery-reviewer","qa-red-team","tech-prd-diagnostician","semantic-consistency-reviewer"}:
    findings=[]
    if role=="delivery-reviewer" and tid=="DELIVERY-REVIEW":
        root_cause="R-REPEAT" if mode=="repeat" else "R-BASE"
        findings=[finding(root_cause,"review gap")]
    elif role=="delivery-reviewer" and tid.startswith("RECHECK-") and tid not in {"RECHECK-R2-DELIVERY-REVIEW"}:
        root_cause="R-REPEAT" if mode=="repeat" else "R-RECHECK"
        findings=[finding(root_cause,"new review gap")]
    # recheck round 2 always accepts
    if tid.startswith("RECHECK-R2-"):
        findings=[]
    review=accepted_review(findings)
    save(review_path,review)
    payload={"schemaVersion":1,"status":"SUCCEEDED","taskId":tid,"role":role,"outputs":[{"path":str(review_path),"kind":"review-result"}],"reviewResultPath":str(review_path),"verdict":review["verdict"],"evidenceRefs":paths}
else:
    payload={"schemaVersion":1,"status":"SUCCEEDED","taskId":tid,"role":role,"outputs":[{"path":"done","kind":"done"}],"evidenceRefs":paths}
save(result_path,payload); print(json.dumps(payload,ensure_ascii=False))
'''

class M3FailureTests(unittest.TestCase):
    def run_cli(self, executable, *args, expect=0):
        proc = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def prepare(self, root, mode):
        requirement=root/'requirement.md'; requirement.write_text('# Requirement\n\nResearch-backed delivery.\n',encoding='utf-8')
        worker=root/'semantic_worker.py'; worker.write_text(WORKER,encoding='utf-8')
        self.run_cli(ORCH,'init','--run-root',root,'--workflow-id','WF-M3','--requirement-name','M3 Demo','--artifact-profile','PRD_ONLY','--prototype-status','NOT_TRIGGERED','--ui-ownership','NONE')
        plan=root/'plan.json'; self.run_cli(ORCH,'build-delivery-plan','--run-root',root,'--out',plan)
        return plan,requirement,worker

    def run_loop(self, root, plan, requirement, worker, mode, expect=1):
        env=os.environ.copy(); env['M3_MODE']=mode
        proc=subprocess.run([sys.executable,str(LOOP),'--run-root',str(root),'--plan',str(plan),'--requirement',str(requirement),'--worker',str(worker),'--runtime','process','--max-tasks','40'],text=True,capture_output=True,env=env)
        self.assertEqual(proc.returncode,expect,proc.stdout+proc.stderr)
        return json.loads(proc.stdout)

    def test_reviewer_returned_creates_repair_and_recheck_round(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'; root.mkdir(); plan,req,worker=self.prepare(root,'new')
            result=self.run_loop(root,plan,req,worker,'new',expect=0)
            self.assertEqual(result['status'],'M1_CONTRACT_COMPLETE')
            data=json.loads(plan.read_text()); tasks={t['taskId']:t for t in data['tasks']}
            self.assertEqual(tasks['DELIVERY-REVIEW']['reviewVerdict'],'RETURNED')
            self.assertEqual(tasks['PRD-REPAIR-01']['status'],'SUCCEEDED')
            self.assertEqual(tasks['RECHECK-DELIVERY-REVIEW']['status'],'SUCCEEDED')
            self.assertEqual(tasks['PRD-REPAIR-R2-01']['status'],'SUCCEEDED')
            self.assertEqual(tasks['RECHECK-R2-DELIVERY-REVIEW']['status'],'SUCCEEDED')
            self.assertEqual(tasks['DELIVERY-HANDOFF']['status'],'SUCCEEDED')

    def test_repeated_root_cause_creates_escalation_and_blocks_quality_exit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'; root.mkdir(); plan,req,worker=self.prepare(root,'repeat')
            result=self.run_loop(root,plan,req,worker,'repeat',expect=1)
            self.assertEqual(result['status'],'FAILED')
            data=json.loads(plan.read_text()); tasks={t['taskId']:t for t in data['tasks']}
            self.assertEqual(tasks['DELIVERY-GATEKEEPER']['status'],'FAILED')
            self.assertIn(tasks['DELIVERY-QUALITY-EXIT']['status'], {'PENDING','FAILED'})
            escalations=list((root/'.agents'/'escalations').glob('*.json'))
            self.assertTrue(escalations)
            self.assertEqual(json.loads(escalations[0].read_text())['status'],'OPEN')

    def test_resume_from_persisted_plan_does_not_repeat_completed_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'run'; root.mkdir(); plan,req,worker=self.prepare(root,'new')
            first=self.run_loop(root,plan,req,worker,'new',expect=1 if False else 0)
            # Run only one task on a fresh plan, then resume.
            root2=Path(td)/'run2'; root2.mkdir(); plan2,req2,worker2=self.prepare(root2,'new')
            partial=subprocess.run([sys.executable,str(LOOP),'--run-root',str(root2),'--plan',str(plan2),'--requirement',str(req2),'--worker',str(worker2),'--runtime','process','--max-tasks','2'],text=True,capture_output=True,env={**os.environ,'M3_MODE':'new'})
            self.assertEqual(partial.returncode,0,partial.stdout+partial.stderr)
            resumed=self.run_loop(root2,plan2,req2,worker2,'new',expect=0)
            self.assertEqual(resumed['status'],'M1_CONTRACT_COMPLETE')
            data=json.loads(plan2.read_text()); statuses={t['taskId']:t['status'] for t in data['tasks']}
            self.assertEqual(statuses['DECISION-READINESS'],'SUCCEEDED')
            self.assertEqual(statuses['PRD-PRODUCE'],'SUCCEEDED')

if __name__=='__main__': unittest.main()
