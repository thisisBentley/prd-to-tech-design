#!/usr/bin/env python3
"""Cross-check Work Plan, Runtime, Review and ReviewGroup state."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACCEPTED={"ACCEPTED","ACCEPTED_WITH_ACTIONS"}
RUNTIME_TO_TASK={"SUCCEEDED":"SUCCEEDED","FAILED":"FAILED","CANCELLED":"FAILED","SPAWNED":"RUNNING","RUNNING":"RUNNING"}

def load(path: Path)->dict[str,Any]: return json.loads(path.read_text(encoding='utf-8'))
def digest(path: Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def resolve(root: Path, value: str)->Path:
    p=Path(value); return p.resolve() if p.is_absolute() else (root/p).resolve()

def review_payload(task: dict[str,Any], root: Path)->tuple[dict[str,Any]|None,Path|None]:
    result_path=task.get('resultPath')
    if not result_path: return None,None
    path=resolve(root,result_path)
    if not path.exists(): return None,path
    data=load(path)
    ref=data.get('reviewResultPath')
    if ref:
        rp=Path(ref); rp=rp if rp.is_absolute() else path.parent/rp
        return load(rp),rp
    return data,path

def validate(run_root: Path, plan_path: Path)->dict[str,Any]:
    plan=load(plan_path); errors=[]; warnings=[]; checks=[]
    tasks={t.get('taskId'):t for t in plan.get('tasks',[])}
    # Runtime record vs task lifecycle and structured result hash.
    for tid,task in tasks.items():
        rrp=task.get('runtimeRecordPath')
        if not rrp: continue
        path=resolve(run_root,rrp)
        if not path.exists(): errors.append(f"{tid}: runtime record missing: {path}"); continue
        record=load(path)
        if record.get('workflowId')!=plan.get('workflowId'): errors.append(f"{tid}: runtime workflowId mismatch")
        expected=RUNTIME_TO_TASK.get(record.get('status'))
        if expected and task.get('status')!=expected: errors.append(f"{tid}: plan status={task.get('status')} runtime status={record.get('status')}")
        srp=record.get('structuredResultPath')
        if srp:
            result_path=resolve(run_root,srp)
            if not result_path.exists(): errors.append(f"{tid}: structured result missing")
            elif record.get('structuredResultSha256') and digest(result_path)!=record['structuredResultSha256']:
                errors.append(f"{tid}: structured result hash mismatch")
    checks.append({'checkId':'STATE.RUNTIME','status':'passed' if not errors else 'failed','observed':f"errors={len(errors)}",'expected':'Work Plan lifecycle matches Runtime Record and result hashes'})
    # Reviewer task -> canonical review result.
    review_errors=[]
    for tid,task in tasks.items():
        if task.get('kind')!='reviewer' or task.get('status') not in {'SUCCEEDED','FAILED'}: continue
        data,path=review_payload(task,run_root)
        if data is None or path is None or not path.exists():
            review_errors.append(f"{tid}: review result missing"); continue
        if task.get('reviewVerdict') and data.get('verdict')!=task['reviewVerdict']:
            review_errors.append(f"{tid}: plan verdict={task.get('reviewVerdict')} review verdict={data.get('verdict')}")
        if task.get('reviewBlockingCount') is not None and int(data.get('blockingCount',0))!=int(task['reviewBlockingCount']):
            review_errors.append(f"{tid}: plan blockingCount mismatch")
        if data.get('verdict') in ACCEPTED and int(data.get('blockingCount',0))!=0:
            review_errors.append(f"{tid}: accepted review has blockers")
    # Review group aggregate recomputation.
    group_errors=[]
    state_path=run_root/'.agents'/'orchestration.json'
    state=load(state_path) if state_path.exists() else {}
    reviews=[]
    for task in tasks.values():
        if task.get('kind')=='reviewer':
            data,_=review_payload(task,run_root)
            if data: reviews.append(data)
    for rel in state.get('reviewGroups',[]):
        gp=resolve(run_root,rel)
        if not gp.exists(): group_errors.append(f"missing review group {rel}"); continue
        group=load(gp); matched=[r for r in reviews if r.get('targetHandoffId')==group.get('targetHandoffId') and r.get('targetRevision')==group.get('targetRevision') and r.get('reviewerRole') in group.get('requiredReviewers',[])]
        verdicts={r.get('reviewerRole'):r.get('verdict') for r in matched}
        if any(v=='BLOCKED' for v in verdicts.values()): expected='BLOCKED'
        elif any(v=='RETURNED' for v in verdicts.values()): expected='RETURNED'
        elif any(v=='INCOMPLETE' for v in verdicts.values()): expected='INCOMPLETE'
        elif all(role in verdicts and verdicts[role] in ACCEPTED for role in group.get('requiredReviewers',[])): expected='ALL_ACCEPTED'
        else: expected='RUNNING' if matched else 'PENDING'
        if group.get('status')!=expected: group_errors.append(f"{group.get('groupId')}: stored={group.get('status')} recomputed={expected}")
    checks.append({'checkId':'STATE.REVIEWS','status':'passed' if not review_errors else 'failed','observed':f"reviewErrors={len(review_errors)}",'expected':'plan review metadata matches canonical review result'})
    checks.append({'checkId':'STATE.REVIEW_GROUPS','status':'passed' if not group_errors else 'failed','observed':f"groupErrors={len(group_errors)}",'expected':'ReviewGroup status equals recomputed aggregate'})
    # Decision/Escalation state must not be hidden.
    state_errors=[]
    for rel in state.get('decisions',[]):
        p=resolve(run_root,rel)
        if not p.exists(): state_errors.append(f"missing decision {rel}"); continue
        d=load(p)
        if d.get('status') not in {'confirmed','closed'}: state_errors.append(f"open decision {d.get('decisionId')}")
    for rel in state.get('escalations',[]):
        p=resolve(run_root,rel)
        if not p.exists(): state_errors.append(f"missing escalation {rel}"); continue
        e=load(p)
        if e.get('status')=='open': state_errors.append(f"open escalation {e.get('escalationId')}")
    checks.append({'checkId':'STATE.DECISIONS_ESCALATIONS','status':'passed' if not state_errors else 'failed','observed':f"errors={len(state_errors)}",'expected':'all decisions/escalations closed before READY'})
    all_errors=errors+review_errors+group_errors+state_errors
    return {'schemaVersion':1,'status':'PASS' if not all_errors else 'BLOCKED','blockingCount':len(all_errors),'checks':checks,'errors':all_errors,'warnings':warnings,'plan':str(plan_path.resolve()),'checkedAt':datetime.now(timezone.utc).isoformat()}

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--run-root',type=Path,required=True); ap.add_argument('--plan',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
    payload=validate(args.run_root.resolve(),args.plan.resolve()); args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':payload['status'],'blockingCount':payload['blockingCount'],'out':str(args.out)},ensure_ascii=False)); return 0 if payload['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
