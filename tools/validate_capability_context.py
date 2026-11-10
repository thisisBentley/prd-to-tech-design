#!/usr/bin/env python3
"""Validate that known capabilities and terminology are sourced and normalized."""
from __future__ import annotations
import argparse, json, re
from datetime import datetime, timezone
from pathlib import Path

def load(p: Path): return json.loads(p.read_text(encoding='utf-8'))
def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--capability',type=Path,required=True); ap.add_argument('--prd',type=Path,required=True); ap.add_argument('--requirement',type=Path); ap.add_argument('--out',type=Path,required=True); args=ap.parse_args()
    cap=load(args.capability); prd=args.prd.read_text(encoding='utf-8'); req=args.requirement.read_text(encoding='utf-8') if args.requirement and args.requirement.exists() else ''
    checks=[]
    required=['capabilityId','canonicalName','status','sourceRefs','confidence','decisionStatus','verificationStatus','verificationEvidenceRefs']
    missing=[k for k in required if not cap.get(k)]
    checks.append({'checkId':'CAPABILITY.SCHEMA','status':'passed' if not missing else 'failed','observed':f'missing={missing}','expected':'required capability context fields present','evidenceRefs':[str(args.capability.resolve())]})
    source_ok=bool(cap.get('sourceRefs')) and bool(cap.get('verificationEvidenceRefs')) and cap.get('verificationStatus') in {'VERIFIED_EXISTING','VERIFIED_EXTENSION','VERIFIED_NEW'} and cap.get('decisionStatus') in {'CONFIRMED','PROVISIONAL'} and cap.get('status') in {'EXISTING','EXTENSION','NEW'}
    checks.append({'checkId':'CAPABILITY.PROVENANCE','status':'passed' if source_ok else 'failed','observed':f"status={cap.get('status')} decision={cap.get('decisionStatus')} sources={len(cap.get('sourceRefs') or [])}",'expected':'sourced capability with non-HOLD decision','evidenceRefs':[str(args.capability.resolve())]})
    terms=[str(cap.get('canonicalName',''))]+[str(x) for x in cap.get('knownAliases',[])]
    mentioned=[term for term in terms if term and (term in prd or term in req)]
    normalized=not mentioned or cap.get('canonicalName') in prd
    checks.append({'checkId':'CAPABILITY.NORMALIZATION','status':'passed' if normalized else 'failed','observed':f"mentioned={mentioned} canonicalInPrd={cap.get('canonicalName') in prd}",'expected':'referenced capability uses canonical name or is not yet used','evidenceRefs':[str(args.prd.resolve()),str(args.capability.resolve())]})
    failed=[c for c in checks if c['status']=='failed']; payload={'schemaVersion':1,'status':'PASS' if not failed else 'NEEDS_FIX','capabilityId':cap.get('capabilityId'),'canonicalName':cap.get('canonicalName'),'blockingCount':len(failed),'checks':checks,'findings':failed,'checkedAt':datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':payload['status'],'blockingCount':len(failed),'out':str(args.out)},ensure_ascii=False)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
