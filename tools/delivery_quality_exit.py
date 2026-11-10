#!/usr/bin/env python3
"""Deterministic Delivery quality exit contract for the P0.7 core."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

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
    failed=[c for c in checks if c['status']=='failed']; payload={'schemaVersion':1,'qualityContract':'delivery-quality-exit-v1','status':'PASS' if not failed else 'BLOCKED','blockingCount':len(failed),'checks':checks,'findings':failed,'evidenceRefs':[str(args.plan.resolve())], 'checkedAt':datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':payload['status'],'blockingCount':len(failed),'out':str(args.out)},ensure_ascii=False)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
