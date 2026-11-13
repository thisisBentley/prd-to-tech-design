#!/usr/bin/env python3
"""Test-only Audit Job worker."""
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--job", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()

envelope = json.loads(args.job.read_text(encoding="utf-8"))
job = envelope["job"]
context = envelope["executorContextId"]
log = os.environ.get("FAKE_AUDIT_CONTEXT_LOG")
if log:
    with Path(log).open("a", encoding="utf-8") as handle:
        handle.write(context + "\n")
if os.environ.get("FAKE_AUDIT_FAIL") == "1":
    raise SystemExit(7)
if os.environ.get("FAKE_AUDIT_MUTATE") == "1":
    Path(envelope["artifactRoot"], "worker-mutated.txt").write_text("changed\n", encoding="utf-8")
bound_rules = job.get("sourcePolicyRuleIds", [])
checks = [
    {
        "checkId": f"{job['jobId']}-{rule_id}",
        "status": "passed",
        "evidenceRefs": ["artifact.txt#fixture"],
        "observed": "fixture worker verified the rule in the frozen artifact",
        "expected": "rule evidence is present",
        "policyRuleIds": [rule_id],
    }
    for rule_id in bound_rules
]
if not checks:
    checks = [{
        "checkId": job["jobId"],
        "status": "passed",
        "evidenceRefs": ["artifact.txt#global"],
        "observed": "fixture worker completed the global cross-rule review",
        "expected": "cross-rule review is coherent",
        "policyRuleIds": [],
    }]
status = "PASS"
findings = []
if os.environ.get("FAKE_AUDIT_BLOCKING") == "1" and bound_rules:
    status = "FAIL"
    findings = [{
        "findingId": f"F-{job['jobId']}",
        "severity": "BLOCKING",
        "title": "fixture blocking audit finding",
        "policyRuleIds": [bound_rules[0]],
        "evidenceRefs": ["artifact.txt#finding"],
        "impact": "the rule is not proven by the frozen evidence",
        "closeCondition": "repair the artifact and rerun the full audit",
        "owner": job["owner"],
    }]
result = {
    "schemaVersion": 1,
    "auditRunId": envelope["auditRunId"],
    "jobId": job["jobId"],
    "auditPlanSha256": envelope["auditPlanSha256"],
    "workflowId": envelope["workflowId"],
    "revision": envelope["revision"],
    "policyLockSha256": envelope["policyLockSha256"],
    "executorType": job["executorType"],
    "executorId": "fake-audit-worker",
    "executorContextId": context,
    "independentContext": True,
    "status": status,
    "checks": checks,
    "findings": findings,
    "checkedAt": "2026-11-13T00:00:00Z",
    "executorTranscript": "fixture worker transcript",
}
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "PASS", "jobId": job["jobId"]}))
