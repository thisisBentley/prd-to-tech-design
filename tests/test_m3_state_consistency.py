import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPTS='scripts' if ROOT.name=='ai-native-delivery' else 'tools'; TOOL=ROOT/SCRIPTS/'validate_delivery_state_consistency.py'
class StateConsistencyTests(unittest.TestCase):
    def run_tool(self,root,plan,expect=0):
        p=subprocess.run([sys.executable,str(TOOL),'--run-root',str(root),'--plan',str(plan),'--out',str(root/'state-check.json')],text=True,capture_output=True)
        self.assertEqual(p.returncode,expect,p.stdout+p.stderr); return json.loads((root/'state-check.json').read_text())
    def setup(self,td):
        root=Path(td)/'run'; root.mkdir(); (root/'.agents'/'runtime').mkdir(parents=True); (root/'.agents'/'reviews').mkdir(parents=True); (root/'.agents'/'review-groups').mkdir(parents=True)
        result=root/'.agents'/'results'/'DELIVERY-REVIEW.result.json'; result.parent.mkdir(parents=True); review=root/'.agents'/'reviews'/'DELIVERY-REVIEW.review.json'
        review.write_text(json.dumps({'schemaVersion':1,'reviewRunId':'R-1','reviewPlanId':'P-1','workflowId':'WF-1','producerRole':'prd-producer','reviewerRole':'delivery-reviewer','reviewType':'independent','targetHandoffId':'H-1','targetRevision':'r1','independentContext':True,'verdict':'ACCEPTED','completionStatus':'complete','checks':[{'checkId':'C','status':'passed','evidenceRefs':['prd'],'observed':'ok','expected':'ok'}],'findings':[],'blockingCount':0,'evidenceRefs':['prd'],'reviewerContextId':'ctx','reviewerTranscript':'t.log','checkedAt':'2026-11-10T00:00:00Z'}))
        result.write_text(json.dumps({'schemaVersion':1,'status':'SUCCEEDED','taskId':'DELIVERY-REVIEW','role':'delivery-reviewer','outputs':[{'path':str(review),'kind':'review-result'}],'reviewResultPath':str(review),'verdict':'ACCEPTED'}))
        record=root/'.agents'/'runtime'/'DELIVERY-REVIEW.json'; record.write_text(json.dumps({'schemaVersion':1,'taskId':'DELIVERY-REVIEW','workflowId':'WF-1','agentId':'a','contextId':'ctx','runtime':'noop','status':'SUCCEEDED','taskManifest':'x','taskManifestSha256':'0'*64,'structuredResultPath':str(result),'structuredResultSha256':hashlib.sha256(result.read_bytes()).hexdigest(),'createdAt':'2026-11-10T00:00:00Z','updatedAt':'2026-11-10T00:00:00Z'}))
        group=root/'.agents'/'review-groups'/'G-1.json'; group.write_text(json.dumps({'schemaVersion':1,'groupId':'G-1','workflowId':'WF-1','stage':'delivery','targetHandoffId':'H-1','targetRevision':'r1','requiredReviewers':['delivery-reviewer'],'status':'PENDING','createdAt':'2026-11-10T00:00:00Z','updatedAt':'2026-11-10T00:00:00Z'}))
        state=root/'.agents'/'orchestration.json'; state.write_text(json.dumps({'schemaVersion':1,'workflowId':'WF-1','status':'IN_PROGRESS','currentStage':'DELIVERY','requirement':{'name':'Demo'},'createdAt':'2026-11-10T00:00:00Z','updatedAt':'2026-11-10T00:00:00Z','handoffs':[],'reviewPlans':[],'reviews':[],'decisions':[],'escalations':[],'reviewGroups':['.agents/review-groups/G-1.json'],'history':[]}))
        plan=root/'plan.json'; plan.write_text(json.dumps({'schemaVersion':1,'planId':'P','workflowId':'WF-1','requirementId':'','artifactProfile':'PRD_ONLY','iteration':'r1','tasks':[{'taskId':'DELIVERY-REVIEW','role':'delivery-reviewer','kind':'reviewer','dependencies':[],'readScope':[],'writeScope':[],'expectedOutputs':['review'],'status':'SUCCEEDED','resultPath':str(result),'runtimeRecordPath':str(record),'reviewVerdict':'ACCEPTED','reviewBlockingCount':0}],'createdAt':'2026-11-10T00:00:00Z'}))
        return root,plan,group
    def test_stale_review_group_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root,plan,group=self.setup(td); data=self.run_tool(root,plan,expect=1); self.assertEqual(data['status'],'BLOCKED'); self.assertTrue(any(c['checkId']=='STATE.REVIEW_GROUPS' and c['status']=='failed' for c in data['checks']))
    def test_recomputed_review_group_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root,plan,group=self.setup(td); g=json.loads(group.read_text()); g['status']='ALL_ACCEPTED'; group.write_text(json.dumps(g)); data=self.run_tool(root,plan); self.assertEqual(data['status'],'PASS')
    def test_runtime_task_status_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root,plan,group=self.setup(td); p=json.loads(plan.read_text()); p['tasks'][0]['status']='FAILED'; plan.write_text(json.dumps(p)); data=self.run_tool(root,plan,expect=1); self.assertTrue(any(c['checkId']=='STATE.RUNTIME' and c['status']=='failed' for c in data['checks']))
if __name__=='__main__': unittest.main()
