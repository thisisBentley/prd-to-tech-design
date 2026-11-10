#!/usr/bin/env python3
"""Deterministic Delivery quality exit contract for the P0.7 core."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from validate_agent_contracts import validate_decision, validate_research_record

def load(path: Path): return json.loads(path.read_text(encoding='utf-8'))
def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--run-root',type=Path,required=True); ap.add_argument('--plan',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
    root=args.run_root.resolve(); plan=load(args.plan); tasks={t.get('taskId'):t for t in plan.get('tasks',[])}; checks=[]
    decision_path=tasks.get('DECISION-READINESS',{}).get('resultPath'); decision=load(Path(decision_path)) if decision_path and Path(decision_path).exists() else {}
    decision_ok=decision.get('readiness')=='READY' and decision.get('decision')=='PROCEED'
    checks.append({'checkId':'QUALITY.DECISION_READINESS','status':'passed' if decision_ok else 'failed','observed':f"readiness={decision.get('readiness')} decision={decision.get('decision')}",'expected':'READY and PROCEED','evidenceRefs':[str(Path(decision_path).resolve())] if decision_path else []})
    review_dir=root/'.agents'/'reviews'; reviews=[]
    if review_dir.exists():
        for p in review_dir.glob('*.review.json'):
            try: reviews.append((p,load(p)))
            except Exception: pass
    blockers=sum(int(d.get('blockingCount',0)) for _,d in reviews)
    reviews_ok=bool(reviews) and blockers==0 and all(d.get('verdict') not in {'RETURNED','BLOCKED','INCOMPLETE'} for _,d in reviews)
    checks.append({'checkId':'QUALITY.REVIEWS','status':'passed' if reviews_ok else 'failed','observed':f"reviews={len(reviews)} blockers={blockers}",'expected':'all required reviews closed with zero blockers','evidenceRefs':[str(p.resolve()) for p,_ in reviews]})
    failed_tasks=[tid for tid,t in tasks.items() if t.get('status')=='FAILED' and tid!='DECISION-READINESS']
    checks.append({'checkId':'QUALITY.WORK_PLAN','status':'passed' if not failed_tasks else 'failed','observed':f"failedTasks={failed_tasks}",'expected':'no failed Delivery tasks','evidenceRefs':[str(args.plan.resolve())]})
    escalations=list((root/'.agents'/'escalations').glob('*.json')) if (root/'.agents'/'escalations').exists() else []
    checks.append({'checkId':'QUALITY.ESCALATIONS','status':'passed' if not escalations else 'failed','observed':f"openEscalations={len(escalations)}",'expected':'zero open escalations','evidenceRefs':[str(p.resolve()) for p in escalations] or [str(root.resolve())]})

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
    failed=[c for c in checks if c['status']=='failed']; payload={'schemaVersion':1,'qualityContract':'delivery-quality-exit-v2','status':'PASS' if not failed else 'BLOCKED','blockingCount':len(failed),'checks':checks,'findings':failed,'evidenceRefs':[str(args.plan.resolve())], 'checkedAt':datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':payload['status'],'blockingCount':len(failed),'out':str(args.out)},ensure_ascii=False)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
