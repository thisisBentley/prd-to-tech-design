#!/usr/bin/env python3
"""Validate that an Overview is a projection of the current SYNCED Pair."""
from __future__ import annotations
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path

def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--pair",type=Path,required=True); ap.add_argument("--overview",type=Path,required=True); ap.add_argument("--prd",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); args=ap.parse_args()
    pair=json.loads(args.pair.read_text()); overview=args.overview.read_text(encoding="utf-8",errors="replace"); prd_hash=hashlib.sha256(args.prd.read_bytes()).hexdigest()
    checks=[
      {"checkId":"OVERVIEW.PAIR_STATUS","status":"passed" if pair.get("pairStatus")=="SYNCED" else "failed","observed":str(pair.get("pairStatus")),"expected":"SYNCED","evidenceRefs":[str(args.pair.resolve())]},
      {"checkId":"OVERVIEW.PRD_HASH","status":"passed" if f'source-prd-sha256" content="{prd_hash}"' in overview else "failed","observed":"source PRD hash present" if prd_hash in overview else "source PRD hash missing","expected":"current PRD hash","evidenceRefs":[str(args.prd.resolve()),str(args.overview.resolve())]},
      {"checkId":"OVERVIEW.REVISION","status":"passed" if str(pair.get("prdRevision","")) in overview else "failed","observed":"revision present" if str(pair.get("prdRevision","")) in overview else "revision missing","expected":"current Pair revision","evidenceRefs":[str(args.pair.resolve()),str(args.overview.resolve())]},
    ]
    failed=[c for c in checks if c["status"]=="failed"]; payload={"schemaVersion":1,"status":"PASS" if not failed else "NEEDS_FIX","pairId":pair.get("pairId"),"pairRevision":pair.get("prdRevision"),"blockingCount":len(failed),"checks":checks,"findings":failed,"checkedAt":datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":payload["status"],"blockingCount":len(failed),"out":str(args.out)},ensure_ascii=False)); return 0 if not failed else 1
if __name__=="__main__": raise SystemExit(main())
