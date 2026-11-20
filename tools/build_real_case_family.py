#!/usr/bin/env python3
"""Build and verify a real AB case family from Trust Kernel and External Gate artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_convergence import canonical_hash, load, now, save, validate_schema_value


def verify_attempts(data: dict, base: Path) -> tuple[list[dict], list[str], dict]:
    attempts: list[dict] = []
    errors: list[str] = []
    artifacts: dict[str, dict] = {}
    for raw in data["attempts"]:
        kernel = load((base / raw["trustKernelRunPath"]).resolve())
        verdict = load((base / raw["externalGateVerdictPath"]).resolve())
        binding = kernel.get("targetBinding") or {}
        route = kernel.get("selectedToolRoute") or {}
        tool = route.get("selectedTool") or {}
        decision = kernel.get("executionDecision") or {}
        attempt = {
            "attemptId": raw["attemptId"],
            "submissionId": raw["submissionId"],
            "role": raw["role"],
            "executionMode": decision.get("mode", "UNKNOWN"),
            "toolId": tool.get("toolId", "UNKNOWN"),
            "targetBinding": binding.get("status", "BLOCKED"),
            "externalVerdict": verdict.get("verdict", "UNKNOWN"),
            "releaseState": verdict.get("releaseState", "BLOCKED"),
            "closureEligible": bool(verdict.get("closureEligible")),
            "artifactHashes": {
                item["path"]: item.get("actualSha256") or item.get("declaredSha256") or item.get("sha256")
                for item in verdict.get("candidateArtifacts", [])
                if item.get("path") and (item.get("actualSha256") or item.get("declaredSha256") or item.get("sha256"))
            },
            "elapsedMinutes": raw.get("elapsedMinutes"),
            "totalInputTokens": raw.get("totalInputTokens"),
            "revisionCount": raw.get("revisionCount"),
            "humanToolRoutingCount": raw.get("humanToolRoutingCount"),
            "outcome": raw["outcome"],
        }
        attempts.append(attempt)
        artifacts[raw["attemptId"]] = {"kernel": kernel, "verdict": verdict}
        if attempt["executionMode"] != "TARGETED_REVISION":
            errors.append(f"{raw['attemptId']}: execution mode is not TARGETED_REVISION")
        if attempt["toolId"] != "gitlab-prd-tool":
            errors.append(f"{raw['attemptId']}: specialist tool is not gitlab-prd-tool")
        if raw["role"] == "FAILURE_BASELINE":
            if attempt["targetBinding"] != "BLOCKED" or attempt["releaseState"] == "CLOSED":
                errors.append(f"{raw['attemptId']}: failure baseline did not remain blocked")
        if raw["role"] == "SUCCESS_REFERENCE":
            if not (attempt["targetBinding"] == "PASS" and attempt["externalVerdict"] == "PASS" and attempt["releaseState"] == "CLOSED" and attempt["closureEligible"]):
                errors.append(f"{raw['attemptId']}: success reference did not close with external PASS")
    return attempts, errors, artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = load(args.input.resolve())
    base = args.input.resolve().parent
    attempts, errors, _ = verify_attempts(data, base)
    payload_without_id = {
        "schemaVersion": 1,
        "caseId": data["caseId"],
        "workflowId": data["workflowId"],
        "businessCase": data["businessCase"],
        "status": "PASS" if not errors else "BLOCKED",
        "attempts": attempts,
        "comparison": {**data["comparison"], "errors": errors},
        "boundaries": data.get("boundaries", []),
        "evidenceRefs": data["evidenceRefs"],
        "createdAt": now(),
    }
    result = {"familyId": "CASE-FAMILY-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    schema_errors = validate_schema_value(result, "real-case-family.schema.json")
    if schema_errors:
        raise ValueError("; ".join(schema_errors))
    save(args.out.resolve(), result)
    print(json.dumps({"status": result["status"], "caseId": result["caseId"], "errors": errors, "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
