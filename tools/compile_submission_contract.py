#!/usr/bin/env python3
"""Compile candidate artifacts, target binding and cached external verdicts into a submission contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from external_gate_cache import load_cached_entries
from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import normalize_url, now, validate_schema_value

STATUS_PRIORITY = {
    "CLOSED": 0,
    "EXTERNAL_GATE_PENDING": 1,
    "EXTERNAL_GATE_FAILED": 2,
    "ENVIRONMENT_BLOCKED": 3,
    "BLOCKED": 4,
}


def check(check_id: str, passed: bool, observed: Any, expected: Any) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
    }


def finding(code: str, message: str, evidence_refs: list[str], severity: str = "BLOCKING") -> dict[str, Any]:
    payload = {
        "severity": severity,
        "code": code,
        "message": message,
        "evidenceRefs": evidence_refs,
    }
    return {"findingId": "SUBMISSION-" + code + "-" + canonical_hash(payload)[:12], **payload}


def artifact_map(items: list[dict[str, Any]], hash_key: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("path") or not item.get(hash_key):
            continue
        result[str(Path(str(item["path"])).resolve())] = str(item[hash_key])
    return result


def evidence_for_gate(request: dict[str, Any], gate_type: str, candidate_artifacts: list[dict[str, Any]], target_report_id: str | None) -> dict[str, Any]:
    return {
        "workflowId": request["workflowId"],
        "candidateRevision": request["candidateRevision"],
        "jiraKey": request["target"]["jiraKey"],
        "gateType": gate_type,
        "tool": request["tool"],
        "candidateArtifacts": [
            {"path": item["path"], "declaredSha256": item["sha256"], "actualSha256": item["sha256"]}
            for item in candidate_artifacts
        ],
        "targetBindingReportId": target_report_id,
    }


def select_gate_result(
    request: dict[str, Any],
    gate_type: str,
    cache_entries: list[dict[str, Any]],
    candidate_artifacts: list[dict[str, Any]],
    target_report_id: str | None,
    current_paths: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = evidence_for_gate(request, gate_type, candidate_artifacts, target_report_id)
    evidence_key = canonical_hash(evidence)
    matching = [item for item in cache_entries if item.get("evidenceKey") == evidence_key]
    findings: list[dict[str, Any]] = []

    if not matching:
        return ({
            "gateType": gate_type,
            "evidenceKey": evidence_key,
            "present": False,
            "status": "MISSING",
            "verdict": None,
            "releaseState": None,
            "verdictId": None,
            "cacheKey": None,
            "recordPath": None,
            "tool": None,
            "candidateArtifacts": [],
        }, findings)

    unique_results = {(item.get("cacheKey"), item.get("verdict"), item.get("releaseState")) for item in matching}
    chosen = sorted(matching, key=lambda item: (str(item.get("cacheKey")), str(item.get("_path"))))[0]
    issues: list[str] = []
    if len(unique_results) > 1:
        issues.append("EXTERNAL_VERDICT_CONFLICT")
        findings.append(finding(
            "EXTERNAL_VERDICT_CONFLICT",
            f"{gate_type} has multiple different verdicts for the same candidate evidence.",
            [str(item.get("_path")) for item in matching],
        ))

    verdict_artifacts = artifact_map(chosen.get("candidateArtifacts", []), "actualSha256")
    declared_artifacts = artifact_map(chosen.get("candidateArtifacts", []), "declaredSha256")
    if declared_artifacts != current_paths or verdict_artifacts != current_paths:
        issues.append("EXTERNAL_GATE_ARTIFACT_HASH_MISMATCH")
        findings.append(finding(
            "EXTERNAL_GATE_ARTIFACT_HASH_MISMATCH",
            f"{gate_type} verdict is not bound to the current candidate artifact set.",
            [str(chosen.get("_path"))],
        ))

    verdict_target = (chosen.get("verdictRecord") or {}).get("targetBinding") or {}
    if not target_report_id or verdict_target.get("reportId") != target_report_id:
        issues.append("EXTERNAL_GATE_TARGET_BINDING_MISMATCH")
        findings.append(finding(
            "EXTERNAL_GATE_TARGET_BINDING_MISMATCH",
            f"{gate_type} verdict references a different target binding report.",
            [str(chosen.get("_path"))],
        ))

    if chosen.get("tool") != request.get("tool"):
        issues.append("EXTERNAL_GATE_TOOL_MISMATCH")
        findings.append(finding(
            "EXTERNAL_GATE_TOOL_MISMATCH",
            f"{gate_type} verdict was produced by a different specialist-tool version.",
            [str(chosen.get("_path"))],
        ))

    return ({
        "gateType": gate_type,
        "evidenceKey": evidence_key,
        "present": True,
        "status": "CONFLICT" if "EXTERNAL_VERDICT_CONFLICT" in issues else ("PASS" if chosen.get("verdict") == "PASS" and chosen.get("releaseState") == "CLOSED" and not issues else str(chosen.get("verdict") or "UNKNOWN")),
        "verdict": chosen.get("verdict"),
        "releaseState": chosen.get("releaseState"),
        "verdictId": chosen.get("verdictId"),
        "cacheKey": chosen.get("cacheKey"),
        "recordPath": chosen.get("_path"),
        "tool": chosen.get("tool"),
        "candidateArtifacts": chosen.get("candidateArtifacts", []),
        "issues": issues,
        "duplicateCount": len(matching),
    }, findings)


def compile_contract(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    request_errors = validate_schema_value(request, "submission-contract-request.schema.json")
    if request_errors:
        raise ValueError("invalid submission-contract request: " + "; ".join(request_errors))

    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    workflow_id = request["workflowId"]
    target = request["target"]
    tool = request["tool"]
    trust_path = Path(request["trustKernelRunPath"]).resolve()
    binding_path = Path(request["targetBindingReportPath"]).resolve()
    cache_dir = Path(request["verdictCacheDir"]).resolve()
    policy_path = Path(request["submissionPolicyPath"]).resolve()

    policy = load(policy_path) if policy_path.is_file() else {}
    policy_errors = validate_schema_value(policy, "submission-policy.schema.json") if policy else ["submission policy is missing"]
    artifact_types = {item["type"] for item in request["candidateArtifacts"]}
    policy_rule = next((
        rule for rule in policy.get("rules", [])
        if tool["toolId"] in rule.get("toolIds", [])
        and set(rule.get("requiredArtifactTypes", [])).issubset(artifact_types)
    ), None)
    expected_gates = list(policy_rule.get("requiredGates", [])) if policy_rule else []
    policy_ok = not policy_errors and policy_rule is not None and request["requiredGates"] == expected_gates
    submission_policy = {
        "path": str(policy_path),
        "policyId": policy.get("policyId"),
        "policySha256": sha256_file(policy_path) if policy_path.is_file() else None,
        "ruleId": (policy_rule or {}).get("ruleId"),
        "requiredGates": expected_gates,
    }
    if policy_errors:
        findings.append(finding("SUBMISSION_POLICY_INVALID", "; ".join(policy_errors), [str(policy_path)]))
    elif policy_rule is None:
        findings.append(finding("SUBMISSION_POLICY_NO_MATCH", "No submission policy rule matches the tool and candidate artifact types.", [str(policy_path)]))
    elif request["requiredGates"] != expected_gates:
        findings.append(finding("SUBMISSION_POLICY_GATE_MISMATCH", "Requested gates do not match the policy-declared required gates.", [str(policy_path)]))

    trust_run = load(trust_path) if trust_path.is_file() else {}
    binding = load(binding_path) if binding_path.is_file() else {}
    trust_errors = validate_schema_value(trust_run, "trust-kernel-run.schema.json") if trust_run else ["trust kernel run is missing"]
    binding_errors = validate_schema_value(binding, "target-binding-report.schema.json") if binding else ["target binding report is missing"]
    if trust_errors:
        findings.append(finding("TRUST_KERNEL_INVALID", "; ".join(trust_errors), [str(trust_path)]))
    if binding_errors:
        findings.append(finding("TARGET_BINDING_INVALID", "; ".join(binding_errors), [str(binding_path)]))

    candidate_artifacts: list[dict[str, Any]] = []
    candidate_hashes_ok = True
    for item in request["candidateArtifacts"]:
        path = Path(item["path"]).resolve()
        actual = sha256_file(path) if path.is_file() else None
        if actual is None:
            candidate_hashes_ok = False
            findings.append(finding("CANDIDATE_ARTIFACT_MISSING", f"Candidate artifact is missing: {path}", [str(path)]))
        candidate_artifacts.append({
            "type": item["type"],
            "path": str(path),
            "sha256": actual,
            "sizeBytes": path.stat().st_size if path.is_file() else None,
        })
    current_paths = artifact_map(candidate_artifacts, "sha256")
    checks.append(check("SUBMISSION.CANDIDATE.HASHES", candidate_hashes_ok, candidate_hashes_ok, True))
    checks.append(check("SUBMISSION.POLICY.REQUIRED_GATES", policy_ok, {
        "requestedGates": request["requiredGates"],
        "policyGates": expected_gates,
        "ruleId": submission_policy.get("ruleId"),
    }, {"requestedGates": expected_gates, "policyGates": expected_gates, "ruleId": submission_policy.get("ruleId")}))

    trust_tool = ((trust_run.get("selectedToolRoute") or {}).get("selectedTool") or {})
    trust_ready = (
        trust_run.get("status") == "READY"
        and trust_run.get("workflowId") == workflow_id
        and (trust_run.get("executionDecision") or {}).get("status") == "CLASSIFIED"
        and trust_tool.get("toolId") == tool["toolId"]
    )
    checks.append(check("SUBMISSION.TRUST_KERNEL.READY", trust_ready, {
        "status": trust_run.get("status"),
        "workflowId": trust_run.get("workflowId"),
        "toolId": trust_tool.get("toolId"),
    }, {"status": "READY", "workflowId": workflow_id, "toolId": tool["toolId"]}))
    if not trust_ready:
        findings.append(finding("TRUST_KERNEL_NOT_READY", "Submission requires a READY Trust Kernel run for the current workflow and tool.", [str(trust_path)]))

    binding_target = binding.get("target") or {}
    binding_ok = (
        binding.get("status") == "PASS"
        and binding.get("workflowId") == workflow_id
        and binding_target.get("jiraKey") == target["jiraKey"]
        and normalize_url(binding_target.get("jiraUrl")) == normalize_url(target["jiraUrl"])
        and binding_target.get("owner") == target["owner"]
    )
    checks.append(check("SUBMISSION.TARGET_BINDING.PASS", binding_ok, binding_target, target))
    if not binding_ok:
        findings.append(finding("TARGET_BINDING_NOT_CURRENT", "Target binding is not PASS or does not match the requested Jira identity.", [str(binding_path)]))

    trust_binding = trust_run.get("targetBinding") or {}
    current_report_id = binding.get("reportId")
    current_binding = bool(current_report_id) and trust_binding.get("reportId") == current_report_id and trust_binding.get("status") == "PASS"
    checks.append(check("SUBMISSION.TARGET_BINDING.CURRENT_REPORT", current_binding, {
        "trustKernelReportId": trust_binding.get("reportId"),
        "currentReportId": current_report_id,
        "trustKernelStatus": trust_binding.get("status"),
    }, {"trustKernelReportId": current_report_id, "currentReportId": current_report_id, "trustKernelStatus": "PASS"}))
    if not current_binding:
        findings.append(finding("TARGET_BINDING_REPORT_DRIFT", "Trust Kernel and submission use different target binding reports.", [str(trust_path), str(binding_path)]))

    binding_artifacts = artifact_map(binding.get("artifacts", []), "sha256")
    binding_hashes_ok = bool(binding_artifacts) and binding_artifacts == current_paths
    checks.append(check("SUBMISSION.TARGET_BINDING.ARTIFACT_HASHES", binding_hashes_ok, binding_artifacts, current_paths))
    if not binding_hashes_ok:
        findings.append(finding("TARGET_BINDING_ARTIFACT_HASH_MISMATCH", "Current candidate hashes differ from the bound target artifacts.", [str(binding_path)]))

    cache_entries, invalid_cache = load_cached_entries(cache_dir)
    cache_valid = not invalid_cache
    checks.append(check("SUBMISSION.VERDICT_CACHE.VALID", cache_valid, {
        "validEntries": len(cache_entries),
        "invalidEntries": len(invalid_cache),
    }, {"invalidEntries": 0}))
    for item in invalid_cache:
        findings.append(finding("EXTERNAL_VERDICT_CACHE_INVALID", "Invalid external verdict cache entry: " + "; ".join(item["errors"]), [item["path"]]))

    gate_results: list[dict[str, Any]] = []
    for gate_type in request["requiredGates"]:
        gate, gate_findings = select_gate_result(request, gate_type, cache_entries, candidate_artifacts, current_report_id, current_paths)
        gate_results.append(gate)
        findings.extend(gate_findings)

    present = all(item["present"] for item in gate_results)
    no_conflict = all(item.get("status") != "CONFLICT" for item in gate_results)
    gate_binding_ok = all(not item.get("issues") for item in gate_results)
    checks.append(check("SUBMISSION.REQUIRED_GATES.PRESENT", present, [item["gateType"] for item in gate_results if item["present"]], request["requiredGates"]))
    checks.append(check("SUBMISSION.EXTERNAL_GATES.CONSISTENT", no_conflict and gate_binding_ok, {
        "conflict": not no_conflict,
        "bindingIssues": [item.get("issues", []) for item in gate_results if item.get("issues")],
    }, {"conflict": False, "bindingIssues": []}))

    hard_block = bool(
        not policy_ok
        or trust_errors
        or binding_errors
        or not candidate_hashes_ok
        or not trust_ready
        or not binding_ok
        or not current_binding
        or not binding_hashes_ok
        or not cache_valid
        or not no_conflict
        or not gate_binding_ok
    )
    if hard_block:
        status = "BLOCKED"
    elif any(item.get("verdict") == "ENVIRONMENT_BLOCKED" for item in gate_results):
        status = "ENVIRONMENT_BLOCKED"
    elif any(item.get("verdict") in {"NEEDS_FIX", "REJECTED"} for item in gate_results):
        status = "EXTERNAL_GATE_FAILED"
    elif not present or any(item.get("verdict") != "PASS" or item.get("releaseState") != "CLOSED" for item in gate_results):
        status = "EXTERNAL_GATE_PENDING"
    else:
        status = "CLOSED"

    if not present:
        missing = [item["gateType"] for item in gate_results if not item["present"]]
        findings.append(finding(
            "REQUIRED_GATE_VERDICT_MISSING",
            "Required external verdicts are missing: " + ", ".join(missing),
            [str(cache_dir)],
        ))
    for gate in gate_results:
        if gate.get("verdict") == "ENVIRONMENT_BLOCKED":
            findings.append(finding("EXTERNAL_GATE_ENVIRONMENT_BLOCKED", f"{gate['gateType']} external gate is environment-blocked.", [gate.get("recordPath") or str(cache_dir)]))
        elif gate.get("verdict") in {"NEEDS_FIX", "REJECTED"}:
            findings.append(finding("EXTERNAL_GATE_FAILED", f"{gate['gateType']} external gate returned {gate['verdict']}.", [gate.get("recordPath") or str(cache_dir)]))

    gate_stable = [
        {
            "gateType": item["gateType"],
            "status": item["status"],
            "verdict": item.get("verdict"),
            "releaseState": item.get("releaseState"),
            "cacheKey": item.get("cacheKey"),
            "evidenceKey": item.get("evidenceKey"),
        }
        for item in gate_results
    ]
    contract_identity = {
        "workflowId": workflow_id,
        "candidateRevision": request["candidateRevision"],
        "target": target,
        "tool": tool,
        "candidateArtifacts": candidate_artifacts,
        "submissionPolicy": submission_policy,
        "trustKernelRunId": trust_run.get("runId"),
        "targetBindingReportId": current_report_id,
        "requiredGates": request["requiredGates"],
        "gateResults": gate_stable,
        "status": status,
    }
    contract_id = "SUBMISSION-CONTRACT-" + canonical_hash(contract_identity)[:16]

    manifest_gate_verdicts = [
        {
            "gateType": item["gateType"],
            "status": item["status"],
            "verdict": item.get("verdict"),
            "releaseState": item.get("releaseState"),
            "verdictId": item.get("verdictId"),
            "cacheKey": item.get("cacheKey"),
            "evidenceKey": item.get("evidenceKey"),
        }
        for item in gate_results
    ]
    manifest_identity = {
        "submissionContractId": contract_id,
        "workflowId": workflow_id,
        "candidateRevision": request["candidateRevision"],
        "target": target,
        "tool": tool,
        "candidateArtifacts": candidate_artifacts,
        "submissionPolicy": submission_policy,
        "requiredGates": request["requiredGates"],
        "gateVerdicts": manifest_gate_verdicts,
        "trustKernelRunId": trust_run.get("runId"),
        "targetBindingReportId": current_report_id,
        "status": status,
    }
    manifest_id = "SUBMISSION-MANIFEST-" + canonical_hash(manifest_identity)[:16]
    content_sha = canonical_hash({"schemaVersion": 1, "manifestId": manifest_id, **manifest_identity})
    created_at = now()
    manifest = {
        "schemaVersion": 1,
        "manifestId": manifest_id,
        **manifest_identity,
        "contentSha256": content_sha,
        "createdAt": created_at,
    }
    contract = {
        "schemaVersion": 1,
        "contractId": contract_id,
        "workflowId": workflow_id,
        "candidateRevision": request["candidateRevision"],
        "target": target,
        "tool": tool,
        "candidateArtifacts": candidate_artifacts,
        "submissionPolicy": submission_policy,
        "trustKernel": {
            "path": str(trust_path),
            "runId": trust_run.get("runId"),
            "status": trust_run.get("status"),
            "toolId": trust_tool.get("toolId"),
            "targetBindingReportId": trust_binding.get("reportId"),
        },
        "targetBinding": {
            "path": str(binding_path),
            "reportId": current_report_id,
            "status": binding.get("status"),
        },
        "verdictCache": {
            "path": str(cache_dir),
            "validEntries": len(cache_entries),
            "invalidEntries": len(invalid_cache),
        },
        "requiredGates": request["requiredGates"],
        "gateResults": gate_results,
        "status": status,
        "closureEligible": status == "CLOSED",
        "checks": checks,
        "findings": findings,
        "submissionManifestSha256": content_sha,
        "createdAt": created_at,
    }
    errors = validate_schema_value(contract, "submission-contract.schema.json")
    if errors:
        raise ValueError("invalid submission contract: " + "; ".join(errors))
    errors = validate_schema_value(manifest, "submission-bundle-manifest.schema.json")
    if errors:
        raise ValueError("invalid submission manifest: " + "; ".join(errors))
    return contract, manifest, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract, manifest, findings = compile_contract(load(args.request.resolve()))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), contract)
    save(args.manifest_out.resolve(), manifest)
    print(json.dumps({
        "status": contract["status"],
        "closureEligible": contract["closureEligible"],
        "contractId": contract["contractId"],
        "manifestId": manifest["manifestId"],
        "gates": {item["gateType"]: item["status"] for item in contract["gateResults"]},
        "findings": len(findings),
        "out": str(args.out.resolve()),
        "manifestOut": str(args.manifest_out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if contract["closureEligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
