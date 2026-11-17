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
unit_ids = list(job.get("unitTargets", []))
artifact_root = Path(envelope["artifactRoot"])
evidence_file = next((path.name for path in sorted(artifact_root.iterdir()) if path.is_file()), "artifact.txt")
checks = [
    {
        "checkId": f"{job['jobId']}-{rule_id}",
        "status": "passed",
        "evidenceRefs": [f"{evidence_file}#L1"],
        "observed": "fixture worker verified the rule in the frozen artifact",
        "expected": "rule evidence is present",
        "policyRuleIds": [rule_id],
        "unitIds": unit_ids,
    }
    for rule_id in bound_rules
]
if not checks:
    checks = [{
        "checkId": job["jobId"],
        "status": "passed",
        "evidenceRefs": [f"{evidence_file}#L1"],
        "observed": "fixture worker completed the global cross-rule review",
        "expected": "cross-rule review is coherent",
        "policyRuleIds": [],
        "unitIds": unit_ids,
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
        "evidenceRefs": [f"{evidence_file}#L1"],
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
