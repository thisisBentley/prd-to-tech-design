#!/usr/bin/env python3
"""Validate a submission contract and its bundle manifest before external submission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, sha256_file
from trust_kernel import now, validate_schema_value


def validate(contract: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend("contract: " + item for item in validate_schema_value(contract, "submission-contract.schema.json"))
    errors.extend("manifest: " + item for item in validate_schema_value(manifest, "submission-bundle-manifest.schema.json"))
    if errors:
        return errors
    if contract.get("status") != "CLOSED":
        errors.append(f"contract status {contract.get('status')} != CLOSED")
    if not contract.get("closureEligible"):
        errors.append("closureEligible must be true")
    if manifest.get("status") != "CLOSED":
        errors.append(f"manifest status {manifest.get('status')} != CLOSED")
    if manifest.get("submissionContractId") != contract.get("contractId"):
        errors.append("manifest submissionContractId does not match contract")
    if manifest.get("contentSha256") != contract.get("submissionManifestSha256"):
        errors.append("contract submissionManifestSha256 does not match manifest contentSha256")
    manifest_without_derived = {
        key: value for key, value in manifest.items()
        if key not in {"contentSha256", "createdAt"}
    }
    if canonical_hash(manifest_without_derived) != manifest.get("contentSha256"):
        errors.append("manifest content hash cannot be replayed")
    for key in ("workflowId", "candidateRevision", "target", "tool", "candidateArtifacts", "submissionPolicy", "requiredGates"):
        if contract.get(key) != manifest.get(key):
            errors.append(f"contract/manifest {key} mismatch")
    if any(item.get("status") == "BLOCKING" for item in contract.get("findings", [])):
        errors.append("blocking submission findings remain")
    gate_status = {item.get("gateType"): item.get("status") for item in contract.get("gateResults", [])}
    for gate in contract.get("requiredGates", []):
        if gate_status.get(gate) != "PASS":
            errors.append(f"required gate {gate} is not PASS")
    for item in contract.get("candidateArtifacts", []):
        path = Path(str(item.get("path", "")))
        if not path.is_file():
            errors.append(f"candidate artifact missing: {path}")
        elif sha256_file(path) != item.get("sha256"):
            errors.append(f"candidate artifact hash drift: {path}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(load(args.contract.resolve()), load(args.manifest.resolve()))
    report = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "checkedAt": now(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
