#!/usr/bin/env python3
"""Validate Research-First records and Decision Card preconditions."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

def load(p: Path): return json.loads(p.read_text(encoding='utf-8'))
def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--research',type=Path); ap.add_argument('--decision',type=Path); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
    checks=[]
    research=load(args.research) if args.research else None
    decision=load(args.decision) if args.decision else None
    if research:
        required=['researchId','workflowId','clue','clueType','researchPlan','sourcesChecked','findings','verdict','decisionRequired','evidenceRefs']
        missing=[k for k in required if research.get(k) in (None,'',[])]
        checks.append({'checkId':'RESEARCH.SCHEMA','status':'passed' if not missing else 'failed','observed':f'missing={missing}','expected':'required research fields present','evidenceRefs':[str(args.research.resolve())]})
        unresolved=[s for s in research.get('sourcesChecked',[]) if s.get('status') in {'UNAVAILABLE','PERMISSION_DENIED'}]
        if research.get('verdict')=='FACT_RESOLVED':
            ok=bool(research.get('evidenceRefs')) and bool(research.get('findings')) and research.get('decisionRequired') is False
        elif research.get('verdict') in {'FACT_CONFLICT','NO_EVIDENCE'}:
            ok=research.get('decisionRequired') is True and bool(research.get('decisionRationale'))
        elif research.get('verdict')=='NEEDS_BUSINESS_DECISION':
            ok=research.get('decisionRequired') is True and bool(research.get('decisionRationale')) and bool(research.get('sourcesChecked'))
        else:
            ok=False
        checks.append({'checkId':'RESEARCH.VERDICT','status':'passed' if ok else 'failed','observed':f"verdict={research.get('verdict')} decisionRequired={research.get('decisionRequired')} unavailableSources={len(unresolved)}",'expected':'verdict, evidence and decision routing are consistent','evidenceRefs':[str(args.research.resolve())]})
    if decision:
        research_ref=decision.get('researchRecordPath')
        checks.append({'checkId':'DECISION.RESEARCH_REF','status':'passed' if research_ref else 'failed','observed':f'researchRecordPath={research_ref}','expected':'Decision Card references a research record','evidenceRefs':[str(args.decision.resolve())]})
        checks.append({'checkId':'DECISION.RESEARCH_VERDICT','status':'passed' if decision.get('researchVerdict')=='NEEDS_BUSINESS_DECISION' else 'failed','observed':f"researchVerdict={decision.get('researchVerdict')}",'expected':'NEEDS_BUSINESS_DECISION','evidenceRefs':[str(args.decision.resolve())]})
        checks.append({'checkId':'DECISION.RATIONALE','status':'passed' if decision.get('whyDecisionRequired') else 'failed','observed':'present' if decision.get('whyDecisionRequired') else 'missing','expected':'whyDecisionRequired explains why existing facts cannot decide','evidenceRefs':[str(args.decision.resolve())]})
    failed=[c for c in checks if c['status']=='failed']; payload={'schemaVersion':1,'status':'PASS' if not failed else 'NEEDS_FIX','blockingCount':len(failed),'checks':checks,'findings':failed,'checkedAt':datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':payload['status'],'blockingCount':len(failed),'out':str(args.out)},ensure_ascii=False)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
