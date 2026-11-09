#!/usr/bin/env python3
"""Turn a root-cause Repair Batch into executable Repair Agent tasks."""
from __future__ import annotations
import argparse, json, secrets
from datetime import datetime, timezone
from pathlib import Path

ROLE_BY_CLASS = {
    "SEMANTIC": "prd-repair-agent",
    "ARTIFACT_CONTRACT": "projection-repair-agent",
    "VISIBLE_INTERACTION": "prototype-repair-agent",
    "RUNTIME": "prototype-repair-agent",
    "EVIDENCE": "evidence-repair-agent",
    "UNKNOWN": "delivery-repair-agent",
}
ARTIFACT_BY_CLASS = {
    "SEMANTIC": ["PRD_DELIVERY.md", "requirements.json", "decision-context.json"],
    "ARTIFACT_CONTRACT": ["PRD_DELIVERY.md", "Prototype.html", "Overview.html"],
    "VISIBLE_INTERACTION": ["Prototype.html", "Overview.html", "PRD_DELIVERY.md"],
    "RUNTIME": ["Prototype.html", "runtime-result.json"],
    "EVIDENCE": ["Gates.md", "Workflow.md", "gate-results"],
    "UNKNOWN": ["affected artifacts from finding"],
}


def load(path): return json.loads(path.read_text(encoding="utf-8"))

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--batch",type=Path,required=True); ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args(); batch=load(args.batch); tasks=[]
    for group in batch.get("groups",[]):
        root=group["rootCauseId"]; cls=group.get("repairClass","UNKNOWN"); task_id="repair-"+root.lower().replace(" ","-").replace("/","-")[:72]
        tasks.append({"taskId":task_id,"rootCauseId":root,"role":ROLE_BY_CLASS.get(cls,"delivery-repair-agent"),"repairClass":cls,"affectedArtifacts":ARTIFACT_BY_CLASS.get(cls,ARTIFACT_BY_CLASS["UNKNOWN"]),"closeConditions":group.get("closeConditions") or ["all source findings closed"],"regressionTests":group.get("regressionTests") or ["rerun affected review scope"],"dependencies":[],"status":"PENDING"})
    result={"schemaVersion":1,"repairPlanId":"repair-plan-"+secrets.token_hex(4),"workflowId":batch.get("workflowId","unknown"),"targetRevision":batch.get("targetRevision","unknown"),"sourceBatch":str(args.batch),"tasks":tasks,"status":"READY" if tasks and batch.get("status")=="READY_FOR_REPAIR" else ("NO_REPAIR" if not tasks else "INCOMPLETE"),"createdAt":datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":result["status"],"plan":str(args.out),"tasks":len(tasks)},ensure_ascii=False,indent=2)); return 0 if result["status"] in {"READY","NO_REPAIR"} else 1
if __name__=="__main__": raise SystemExit(main())
