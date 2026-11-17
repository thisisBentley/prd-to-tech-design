#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--job", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
env = json.loads(args.job.read_text())
job = env["job"]
prd = Path(env["artifactRoot"]) / "PRD_DELIVERY.md"
passed = "# repaired" in prd.read_text(encoding="utf-8")
rules = job.get("sourcePolicyRuleIds", [])
unit_ids = list(job.get("unitTargets", []))
checks = [{
    "checkId": f"{job['jobId']}-{rule}", "status": "passed" if passed else "failed",
    "evidenceRefs": ["PRD_DELIVERY.md#repaired" if passed else "PRD_DELIVERY.md#unrepaired"],
    "observed": "PRD contains the repaired marker" if passed else "PRD still lacks the repaired marker",
    "expected": "repair marker present", "policyRuleIds": [rule], "unitIds": unit_ids,
} for rule in rules]
if not checks:
    checks = [{"checkId": job["jobId"], "status": "passed" if passed else "failed", "evidenceRefs": ["PRD_DELIVERY.md#L1"], "observed": "cross-rule review found the repaired package coherent", "expected": "global review", "policyRuleIds": [], "unitIds": unit_ids}]
findings = [] if passed else [{
    "findingId": "F-REPAIR-ME", "severity": "BLOCKING", "title": "repair marker missing",
    "policyRuleIds": rules[:1], "evidenceRefs": ["PRD_DELIVERY.md#unrepaired"],
    "impact": "candidate remains unrepaired", "closeCondition": "add repair marker", "owner": "prd-repair-agent",
}]
result = {
    "schemaVersion": 1, "auditRunId": env["auditRunId"], "jobId": job["jobId"],
    "auditPlanSha256": env["auditPlanSha256"], "workflowId": env["workflowId"], "revision": env["revision"],
    "policyLockSha256": env["policyLockSha256"], "executorType": job["executorType"],
    "executorId": "cycle-audit-worker", "executorContextId": env["executorContextId"],
    "independentContext": True, "status": "PASS" if passed else "FAIL", "checks": checks,
    "findings": findings, "checkedAt": "2026-11-16T00:00:00Z", "executorTranscript": "cycle fixture",
}
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
