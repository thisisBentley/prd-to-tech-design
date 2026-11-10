#!/usr/bin/env python3
"""Audit and safely recover an interrupted Delivery Work Plan."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_TO_TASK={"SUCCEEDED":"SUCCEEDED","FAILED":"FAILED","CANCELLED":"FAILED","SPAWNED":"FAILED","RUNNING":"FAILED"}
def load(path:Path)->dict[str,Any]: return json.loads(path.read_text(encoding='utf-8'))
def save(path:Path,data:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def resolve(root:Path,value:str)->Path:
    p=Path(value); return p.resolve() if p.is_absolute() else (root/p).resolve()

def recover(root:Path,plan_path:Path,report_path:Path|None=None)->dict[str,Any]:
    plan=load(plan_path); tasks=plan.get('tasks',[]); task_map={t.get('taskId'):t for t in tasks}; actions=[]; errors=[]
    for task in tasks:
        tid=task.get('taskId')
        status=task.get('status')
        if status=='RUNNING':
            record_path=task.get('runtimeRecordPath')
            if not record_path:
                task['status']='FAILED'; task['error']='interrupted before runtime record was persisted'; task['recoverable']=True
                actions.append({'taskId':tid,'action':'MARK_RERUNNABLE','reason':'missing runtime record'}); continue
            rp=resolve(root,record_path)
            if not rp.exists():
                task['status']='FAILED'; task['error']='interrupted: runtime record missing'; task['recoverable']=True
                actions.append({'taskId':tid,'action':'MARK_RERUNNABLE','reason':'runtime record missing'}); continue
            record=load(rp); runtime_status=record.get('status')
            mapped=RUNTIME_TO_TASK.get(runtime_status)
            if runtime_status=='SUCCEEDED':
                result_value=record.get('structuredResultPath')
                if not result_value:
                    task['status']='FAILED'; task['error']='runtime succeeded but no structured result path'; task['recoverable']=True
                    actions.append({'taskId':tid,'action':'MARK_RERUNNABLE','reason':'missing structured result path'})
                else:
                    result=resolve(root,result_value)
                    if not result.exists() or record.get('structuredResultSha256')!=sha(result):
                        task['status']='FAILED'; task['error']='runtime result missing or hash mismatch'; task['recoverable']=True
                        actions.append({'taskId':tid,'action':'MARK_RERUNNABLE','reason':'result missing or hash mismatch'})
                    else:
                        task['status']='SUCCEEDED'; task['resultPath']=str(result); task['completedAt']=datetime.now(timezone.utc).isoformat(); task.pop('error',None)
                        actions.append({'taskId':tid,'action':'RECOVER_SUCCEEDED','runtimeRecord':str(rp)})
            elif mapped:
                task['status']=mapped; task['error']=record.get('error') or f'interrupted runtime status={runtime_status}'; task['recoverable']=True; task['completedAt']=datetime.now(timezone.utc).isoformat()
                actions.append({'taskId':tid,'action':'MARK_RERUNNABLE','reason':task['error']})
            else:
                task['status']='FAILED'; task['error']=f'unknown runtime status={runtime_status}'; task['recoverable']=True
                actions.append({'taskId':tid,'action':'MARK_RERUNNABLE','reason':task['error']})
    # Verify every task that claims success has complete evidence.
    for task in tasks:
        if task.get('status')!='SUCCEEDED': continue
        tid=task.get('taskId')
        rp=task.get('runtimeRecordPath'); result=task.get('resultPath')
        if rp:
            p=resolve(root,rp)
            if not p.exists(): errors.append(f'{tid}: succeeded task runtime record missing')
        if result:
            p=resolve(root,result)
            if not p.exists(): errors.append(f'{tid}: succeeded task result missing')
        for dep in task.get('dependencies',[]):
            if task_map.get(dep,{}).get('status')!='SUCCEEDED': errors.append(f'{tid}: dependency {dep} is not succeeded')
    save(plan_path,plan)
    report={'schemaVersion':1,'status':'PASS' if not errors else 'BLOCKED','workflowId':plan.get('workflowId'),'recoveredTasks':len(actions),'actions':actions,'errors':errors,'checkedAt':datetime.now(timezone.utc).isoformat()}
    target=report_path or root/'.agents'/'recovery'/'latest.json'; save(target,report); return {**report,'reportPath':str(target.resolve())}

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--run-root',type=Path,required=True); ap.add_argument('--plan',type=Path,required=True); ap.add_argument('--out',type=Path); args=ap.parse_args()
    result=recover(args.run_root.resolve(),args.plan.resolve(),args.out.resolve() if args.out else None); print(json.dumps({'status':result['status'],'recoveredTasks':result['recoveredTasks'],'errors':result['errors'],'report':result['reportPath']},ensure_ascii=False)); return 0 if result['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
