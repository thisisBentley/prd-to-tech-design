#!/usr/bin/env python3
"""Reconcile collected review results into a Delivery repair batch and plan state."""
from __future__ import annotations
import argparse, json, secrets
from datetime import datetime, timezone
from pathlib import Path
from consolidate_findings import consolidate


def now(): return datetime.now(timezone.utc).isoformat()
def load(p): return json.loads(p.read_text(encoding="utf-8"))
def save(p,d): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def reconcile(run_root: Path, plan_path: Path) -> dict:
    plan=load(plan_path); workflow=plan["workflowId"]; revision=plan["iteration"]
    review_dir=run_root/".agents"/"reviews"
    reviews=[]
    if review_dir.exists():
        for path in sorted(review_dir.glob("*.json")):
            try: data=load(path)
            except Exception: continue
            if data.get("workflowId") == workflow and data.get("targetRevision") == revision and data.get("verdict"):
                reviews.append(path)
    reviewer_roles={t["role"] for t in plan.get("tasks",[]) if t.get("kind")=="reviewer"}
    matched=[p for p in reviews if load(p).get("reviewerRole") in reviewer_roles]
    repair_dir=run_root/".agents"/"repair-batches"
    repair_dir.mkdir(parents=True,exist_ok=True)
    if not matched:
        return {"status":"WAITING","reason":"no matching review results","workflowId":workflow,"revision":revision}
    batch={
        "schemaVersion":1,
        "batchId":"repair-batch-"+secrets.token_hex(4),
        "workflowId":workflow,
        "targetRevision":revision,
        "sourceReviews":[str(p) for p in matched],
        "groups":[],
        "blockingCount":0,
        "status":"NO_FINDINGS",
        "createdAt":now(),
    }
    # Reuse the canonical consolidator; it returns INCOMPLETE on mixed inputs.
    batch=consolidate(matched)
    batch_path=repair_dir/f"{batch['batchId']}.json"
    save(batch_path,batch)
    completed_roles={load(p).get("reviewerRole") for p in matched}
    returned_reviewers=[]
    for task in plan.get("tasks",[]):
        if task.get("kind")=="reviewer" and task.get("role") in completed_roles:
            result_path=next(p for p in matched if load(p).get("reviewerRole")==task["role"])
            review_data=load(result_path)
            task["status"]="SUCCEEDED"; task["completedAt"]=now(); task["resultPath"]=str(result_path)
            task["reviewVerdict"]=review_data.get("verdict")
            task["reviewBlockingCount"]=int(review_data.get("blockingCount",0))
            if review_data.get("verdict") in {"RETURNED","BLOCKED","INCOMPLETE"}:
                returned_reviewers.append(task["role"])
        if task.get("taskId")=="FINDING-CONSOLIDATE":
            task["status"]="SUCCEEDED" if batch["status"] in {"READY_FOR_REPAIR","NO_FINDINGS"} else "FAILED"
            task["completedAt"]=now(); task["resultPath"]=str(batch_path); task["error"] = "mixed workflow/revision inputs" if batch["status"]=="INCOMPLETE" else task.get("error")
    save(plan_path,plan)
    return {"status":"PASS" if batch["status"] in {"READY_FOR_REPAIR","NO_FINDINGS"} else "INCOMPLETE","workflowId":workflow,"revision":revision,"reviewCount":len(matched),"repairBatch":str(batch_path),"blockingCount":batch["blockingCount"],"batchStatus":batch["status"],"returnedReviewers":returned_reviewers}


def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--run-root",type=Path,required=True); ap.add_argument("--plan",type=Path,required=True)
    args=ap.parse_args(); result=reconcile(args.run_root.resolve(),args.plan.resolve()); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["status"] in {"PASS","WAITING"} else 1
if __name__=="__main__": raise SystemExit(main())
