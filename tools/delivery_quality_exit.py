#!/usr/bin/env python3
"""Deterministic Delivery quality exit contract for the P0.7 core."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from validate_agent_contracts import validate_decision, validate_research_record
from validate_delivery_state_consistency import validate as validate_state_consistency

def load(path: Path): return json.loads(path.read_text(encoding='utf-8'))

def review_payload(task: dict):
    result_path=task.get('resultPath')
    if not result_path: return None, None
    path=Path(result_path)
    if not path.exists(): return None, path
    try: payload=load(path)
    except Exception: return None, path
    ref=payload.get('reviewResultPath')
    if ref:
        review_path=Path(ref)
        if not review_path.is_absolute(): review_path=path.parent/review_path
        try: return load(review_path), review_path
        except Exception: return None, review_path
    return payload, path

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--run-root',type=Path,required=True); ap.add_argument('--plan',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
    root=args.run_root.resolve(); plan=load(args.plan); tasks={t.get('taskId'):t for t in plan.get('tasks',[])}; checks=[]
    decision_path=tasks.get('DECISION-READINESS',{}).get('resultPath'); decision=load(Path(decision_path)) if decision_path and Path(decision_path).exists() else {}
    decision_ok=decision.get('readiness')=='READY' and decision.get('decision')=='PROCEED'
    checks.append({'checkId':'QUALITY.DECISION_READINESS','status':'passed' if decision_ok else 'failed','observed':f"readiness={decision.get('readiness')} decision={decision.get('decision')}",'expected':'READY and PROCEED','evidenceRefs':[str(Path(decision_path).resolve())] if decision_path else []})
    latest_by_role={}
    for order,task in enumerate(plan.get('tasks',[])):
        if task.get('kind') != 'reviewer' or not task.get('resultPath'):
            continue
        latest_by_role[task.get('role')]=(order,task)
    reviews=[]; review_errors=[]; reviews_by_role={}
    for role,(_,task) in sorted(latest_by_role.items(), key=lambda item:item[1][0]):
        data,path=review_payload(task)
        if data is None:
            review_errors.append(f"{role}: review result missing"); continue
        reviews.append((path,data)); reviews_by_role[role]=(path,data)
        if data.get('verdict') in {'RETURNED','BLOCKED','INCOMPLETE'} or int(data.get('blockingCount',0)) != 0:
            review_errors.append(f"{role}: verdict={data.get('verdict')} blockers={data.get('blockingCount')}")
    blockers=sum(int(d.get('blockingCount',0)) for _,d in reviews)
    reviews_ok=bool(reviews) and not review_errors
    checks.append({'checkId':'QUALITY.REVIEWS','status':'passed' if reviews_ok else 'failed','observed':f"latestRoles={len(reviews)} blockers={blockers} errors={len(review_errors)}",'expected':'latest review per role is closed with zero blockers','evidenceRefs':[str(p.resolve()) for p,_ in reviews] or [str(root.resolve())]})
    semantic_input_path=root/'.agents'/'context'/'semantic-consistency-input.json'
    capability_context_path=root/'.agents'/'context'/'capability-context.json'
    semantic_required=semantic_input_path.exists() or capability_context_path.exists()
    semantic_entry=reviews_by_role.get('semantic-consistency-reviewer')
    semantic_errors=[]
    semantic_axes={'SEMANTIC.TERMINOLOGY','SEMANTIC.CAPABILITY','SEMANTIC.STATE','SEMANTIC.PERMISSION','SEMANTIC.AUTHORITY_SYNC','SEMANTIC.PROVENANCE'}
    if semantic_required and not semantic_input_path.exists():
        semantic_errors.append('semantic-consistency-input.json missing')
    if semantic_required and semantic_entry is None:
        semantic_errors.append('semantic-consistency-reviewer result missing')
    elif semantic_required:
        semantic_review=semantic_entry[1]
        passed_axes={c.get('checkId') for c in semantic_review.get('checks',[]) if c.get('status')=='passed'}
        if semantic_review.get('verdict')!='ACCEPTED' or int(semantic_review.get('blockingCount',1))!=0:
            semantic_errors.append(f"verdict={semantic_review.get('verdict')} blockers={semantic_review.get('blockingCount')}")
        if not semantic_axes <= passed_axes:
            semantic_errors.append('missing axes='+','.join(sorted(semantic_axes-passed_axes)))
    semantic_status='not_applicable' if not semantic_required else ('passed' if not semantic_errors else 'failed')
    semantic_refs=[str(semantic_input_path.resolve())] if semantic_input_path.exists() else []
    if semantic_entry: semantic_refs.append(str(semantic_entry[0].resolve()))
    checks.append({'checkId':'QUALITY.SEMANTIC_REVIEW','status':semantic_status,'observed':f"required={semantic_required} errors={semantic_errors}",'expected':'all six semantic axes executed and passed when capability or semantic context exists','evidenceRefs':semantic_refs or [str(root.resolve())]})
    failed_tasks=[tid for tid,t in tasks.items() if t.get('status')=='FAILED' and tid!='DECISION-READINESS']
    checks.append({'checkId':'QUALITY.WORK_PLAN','status':'passed' if not failed_tasks else 'failed','observed':f"failedTasks={failed_tasks}",'expected':'no failed Delivery tasks','evidenceRefs':[str(args.plan.resolve())]})
    escalations=list((root/'.agents'/'escalations').glob('*.json')) if (root/'.agents'/'escalations').exists() else []
    checks.append({'checkId':'QUALITY.ESCALATIONS','status':'passed' if not escalations else 'failed','observed':f"openEscalations={len(escalations)}",'expected':'zero open escalations','evidenceRefs':[str(p.resolve()) for p in escalations] or [str(root.resolve())]})

    capability_registry_path=root/'.agents'/'context'/'research-capabilities.json'
    capability_registry={}
    capability_registry_errors=[]
    if capability_registry_path.exists():
        try:
            capability_registry=load(capability_registry_path)
            sources=capability_registry.get('sources') or []
            configured=sum(1 for s in sources if s.get('configured'))
            available=sum(1 for s in sources if s.get('status')=='CONFIGURED_AVAILABLE')
            capability_registry_errors=[f"{s.get('source')}: {s.get('error')}" for s in sources if s.get('status')=='CONFIGURED_ERROR'] if configured>0 and available==0 else []
        except Exception as exc:
            capability_registry_errors=[f"{capability_registry_path}: {exc}"]
    checks.append({'checkId':'QUALITY.RESEARCH_CAPABILITIES','status':'passed' if not capability_registry_errors else 'failed','observed':f"researchFirstRequired={capability_registry.get('researchFirstRequired')} errors={len(capability_registry_errors)}",'expected':'configured sources probe successfully; not-configured sources do not block','evidenceRefs':[str(capability_registry_path.resolve())] if capability_registry_path.exists() else [str(root.resolve())]})

    research_records=[]
    research_errors=[]
    research_dir=root/'.agents'/'research'
    if research_dir.exists():
        for p in research_dir.glob('*.json'):
            try:
                item=load(p); research_records.append((p,item)); research_errors.extend(validate_research_record(item,str(p)))
            except Exception as exc:
                research_errors.append(f"{p}: {exc}")
    checks.append({'checkId':'QUALITY.RESEARCH_RECORDS','status':'passed' if not research_errors else 'failed','observed':f"records={len(research_records)} errors={len(research_errors)}",'expected':'all research records valid','evidenceRefs':[str(p.resolve()) for p,_ in research_records] or [str(root.resolve())]})

    decision_cards=[]
    decision_errors=[]
    open_decisions=[]
    decision_dir=root/'.agents'/'decisions'
    if decision_dir.exists():
        for p in decision_dir.glob('*.json'):
            try:
                item=load(p); decision_cards.append((p,item)); decision_errors.extend(validate_decision(item,str(p)))
                if item.get('status') not in {'confirmed','closed'}:
                    open_decisions.append(str(p.resolve()))
                research_ref=item.get('researchRecordPath')
                if research_ref:
                    research_path=Path(research_ref)
                    if not research_path.is_absolute():
                        research_path=p.parent/research_path
                        if not research_path.exists(): research_path=root/research_ref
                    if not research_path.exists():
                        decision_errors.append(f"{p}: research record not found: {research_ref}")
                    else:
                        research=load(research_path)
                        if research.get('verdict')!='NEEDS_BUSINESS_DECISION' or research.get('decisionRequired') is not True:
                            decision_errors.append(f"{p}: Decision Card must reference NEEDS_BUSINESS_DECISION research")
            except Exception as exc:
                decision_errors.append(f"{p}: {exc}")
    decision_ok=not decision_errors and not open_decisions
    checks.append({'checkId':'QUALITY.DECISIONS','status':'passed' if decision_ok else 'failed','observed':f"cards={len(decision_cards)} open={len(open_decisions)} errors={len(decision_errors)}",'expected':'all decisions closed and research-backed','evidenceRefs':[str(p.resolve()) for p,_ in decision_cards] or [str(root.resolve())]})
    evidence_errors=[]
    for task in plan.get('tasks',[]):
        if task.get('status')=='SUCCEEDED':
            for key in ('resultPath','runtimeRecordPath'):
                if task.get(key) and not Path(task[key]).exists():
                    evidence_errors.append(f"{task.get('taskId')}: missing {key}")
    checks.append({'checkId':'QUALITY.EVIDENCE','status':'passed' if not evidence_errors else 'failed','observed':f"missingEvidence={len(evidence_errors)}",'expected':'all succeeded tasks retain result and runtime evidence','evidenceRefs':[str(args.plan.resolve())]})

    prd_path=None
    producer=tasks.get('PRD-PRODUCE') or {}
    if producer.get('resultPath') and Path(producer['resultPath']).exists():
        try:
            producer_result=load(Path(producer['resultPath']))
            prd_path=producer_result.get('prdArtifactPath') or producer.get('prdArtifactPath')
        except Exception:
            pass
    fr_count=ac_count=0
    if prd_path and Path(prd_path).exists():
        import re
        text=Path(prd_path).read_text(encoding='utf-8')
        fr_count=len(set(re.findall(r'\bFR-[0-9]{3}\b',text)))
        ac_count=len(set(re.findall(r'\bAC-[0-9]{3}\b',text)))
    traceability_ok=fr_count>0 and ac_count>0
    checks.append({'checkId':'QUALITY.TRACEABILITY','status':'passed' if traceability_ok else 'failed','observed':f"FR={fr_count} AC={ac_count}",'expected':'PRD contains traceable FR and AC identifiers','evidenceRefs':[str(Path(prd_path).resolve())] if prd_path and Path(prd_path).exists() else [str(root.resolve())]})

    metrics={'reviewRoles':len(reviews),'blockingCount':blockers,'failedTasks':len(failed_tasks),'openEscalations':len(escalations),'researchRecords':len(research_records),'openDecisions':len(open_decisions),'frCount':fr_count,'acCount':ac_count}
    state_consistency=validate_state_consistency(root,args.plan)
    checks.append({'checkId':'QUALITY.STATE_CONSISTENCY','status':'passed' if state_consistency.get('status')=='PASS' else 'failed','observed':f"status={state_consistency.get('status')} errors={state_consistency.get('blockingCount')}",'expected':'Work Plan, Runtime, Review and ReviewGroup state are consistent','evidenceRefs':[str(args.plan.resolve())]})
    failed=[c for c in checks if c['status']=='failed']; payload={'schemaVersion':1,'qualityContract':'delivery-quality-exit-v2','status':'PASS' if not failed else 'BLOCKED','blockingCount':len(failed),'metrics':metrics,'checks':checks,'findings':failed,'stateConsistency':state_consistency,'evidenceRefs':[str(args.plan.resolve())], 'checkedAt':datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':payload['status'],'blockingCount':len(failed),'out':str(args.out)},ensure_ascii=False)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
