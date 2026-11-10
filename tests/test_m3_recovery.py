import hashlib,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPTS='scripts' if ROOT.name=='ai-native-delivery' else 'tools'; TOOL=ROOT/SCRIPTS/'recover_delivery_run.py'; LOOP=ROOT/SCRIPTS/'delivery_loop.py'
class RecoveryTests(unittest.TestCase):
    def run_tool(self,root,plan,expect=0):
        p=subprocess.run([sys.executable,str(TOOL),'--run-root',str(root),'--plan',str(plan)],text=True,capture_output=True)
        self.assertEqual(p.returncode,expect,p.stdout+p.stderr); return json.loads(p.stdout)
    def setup(self,td):
        root=Path(td)/'run'; root.mkdir(); (root/'.agents'/'runtime').mkdir(parents=True); (root/'.agents'/'results').mkdir(parents=True)
        plan=root/'plan.json'; plan.write_text(json.dumps({'schemaVersion':1,'planId':'P','workflowId':'WF-1','requirementId':'','artifactProfile':'PRD_ONLY','iteration':'r1','createdAt':'2026-11-10T00:00:00Z','tasks':[{'taskId':'T-1','role':'prd-producer','kind':'producer','dependencies':[],'readScope':[],'writeScope':[],'expectedOutputs':['x'],'status':'RUNNING','runtimeRecordPath':'.agents/runtime/T-1.json'}]}))
        result=root/'.agents'/'results'/'T-1.result.json'; result.write_text(json.dumps({'schemaVersion':1,'status':'SUCCEEDED','outputs':[{'path':'x'}]}))
        record=root/'.agents'/'runtime'/'T-1.json'; record.write_text(json.dumps({'schemaVersion':1,'taskId':'T-1','workflowId':'WF-1','agentId':'a','contextId':'ctx','runtime':'process','status':'SUCCEEDED','taskManifest':'x','taskManifestSha256':'0'*64,'structuredResultPath':str(result),'structuredResultSha256':hashlib.sha256(result.read_bytes()).hexdigest(),'createdAt':'2026-11-10T00:00:00Z','updatedAt':'2026-11-10T00:00:00Z'}))
        return root,plan,result,record
    def test_running_task_with_complete_runtime_result_recovers(self):
        with tempfile.TemporaryDirectory() as td:
            root,plan,result,record=self.setup(td); out=self.run_tool(root,plan); self.assertEqual(out['status'],'PASS'); data=json.loads(plan.read_text()); self.assertEqual(data['tasks'][0]['status'],'SUCCEEDED'); report=json.loads((root/'.agents'/'recovery'/'latest.json').read_text()); self.assertEqual(report['actions'][0]['action'],'RECOVER_SUCCEEDED')
    def test_corrupt_succeeded_result_blocks_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root,plan,result,record=self.setup(td); self.run_tool(root,plan); result.unlink(); out=self.run_tool(root,plan,expect=1); self.assertEqual(out['status'],'BLOCKED')
    def test_loop_refuses_to_continue_when_recovery_audit_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root,plan,result,record=self.setup(td); self.run_tool(root,plan); result.unlink(); requirement=root/'requirement.md'; requirement.write_text('# Requirement\n'); p=subprocess.run([sys.executable,str(LOOP),'--run-root',str(root),'--plan',str(plan),'--requirement',str(requirement),'--worker',str(ROOT/SCRIPTS/'deterministic_worker.py'),'--runtime','process'],text=True,capture_output=True); self.assertEqual(p.returncode,1,p.stdout+p.stderr); data=json.loads(p.stdout); self.assertEqual(data['status'],'RECOVERY_BLOCKED')
if __name__=='__main__': unittest.main()
