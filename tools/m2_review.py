#!/usr/bin/env python3
"""Run deterministic U1/U2 and Final Package checks for a synchronized M2 bundle."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

def load(p): return json.loads(p.read_text())
def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--pair",type=Path,required=True); ap.add_argument("--preflight",type=Path,required=True); ap.add_argument("--runtime",type=Path,required=True); ap.add_argument("--consistency",type=Path,required=True); ap.add_argument("--overview-gate",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); args=ap.parse_args()
    pair=load(args.pair); pre=load(args.preflight); runtime=load(args.runtime); consistency=load(args.consistency); overview=load(args.overview_gate)
    checks=[]
    for cid, ok, observed, expected, ref in [
      ("M2.PAIR",pair.get("pairStatus")=="SYNCED",str(pair.get("pairStatus")),"SYNCED",args.pair),
      ("U1.PROTOTYPE",pre.get("status")=="PASS",str(pre.get("status")),"PASS",args.preflight),
      ("U1.RUNTIME",runtime.get("status")=="PASS" and not runtime.get("consoleErrors") and not runtime.get("pageErrors") and not runtime.get("requestFailures"),str(runtime.get("status")),"PASS with zero console errors",args.runtime),
      ("U2.CONSISTENCY",consistency.get("status")=="PASS" and consistency.get("blockingCount",1)==0,f'{consistency.get("status")} blockers={consistency.get("blockingCount")}',"PASS with zero blockers",args.consistency),
      ("O1.PROJECTION",overview.get("status")=="PASS" and overview.get("blockingCount",1)==0,f'{overview.get("status")} blockers={overview.get("blockingCount")}',"PASS with zero blockers",args.overview_gate),
    ]: checks.append({"checkId":cid,"status":"passed" if ok else "failed","observed":observed,"expected":expected,"evidenceRefs":[str(ref.resolve())]})
    failed=[c for c in checks if c["status"]=="failed"]; payload={"schemaVersion":1,"reviewType":"M2_FINAL_PACKAGE","verdict":"ACCEPTED" if not failed else "BLOCKED","completionStatus":"complete","blockingCount":len(failed),"checks":checks,"findings":failed,"evidenceRefs":[str(args.pair.resolve()),str(args.preflight.resolve()),str(args.runtime.resolve()),str(args.consistency.resolve()),str(args.overview_gate.resolve())],"checkedAt":datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":payload["verdict"],"blockingCount":len(failed),"out":str(args.out)},ensure_ascii=False)); return 0 if not failed else 1
if __name__=="__main__": raise SystemExit(main())
