#!/usr/bin/env python3
"""Compile and validate a versioned Agent contract release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_contracts import ROOT, canonical_hash, load, now, save, sha256_file, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True, help="Source contract profile JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Compiled contract release JSON.")
    parser.add_argument("--generated-at", help="Stable timestamp for reproducible builds.")
    args = parser.parse_args()
    profile_path = args.profile.resolve()
    profile = load(profile_path)
    contracts = profile.get("contracts", [])
    if not isinstance(contracts, list) or not contracts:
        raise SystemExit("profile must contain a non-empty contracts array")
    errors: list[str] = []
    seen: set[str] = set()
    for index, contract in enumerate(contracts):
        contract_errors = validate_schema_value(contract, "agent-task-contract.schema.json")
        errors.extend(f"contracts[{index}]: {item}" for item in contract_errors)
        contract_id = str(contract.get("contractId", ""))
        if contract_id in seen:
            errors.append(f"duplicate contractId: {contract_id}")
        seen.add(contract_id)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    try:
        profile_display = profile_path.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        profile_display = str(profile_path)
    release: dict[str, Any] = {
        "schemaVersion": 1,
        "releaseId": str(profile["releaseId"]),
        "releaseVersion": str(profile["releaseVersion"]),
        "status": str(profile.get("status", "PUBLISHED")),
        "sourceProfilePath": profile_display,
        "sourceProfileSha256": sha256_file(profile_path),
        "contracts": contracts,
        "contractHashes": {item["contractId"]: canonical_hash(item) for item in contracts},
        "compiledAt": args.generated_at or now(),
    }
    release_errors = validate_schema_value(release, "agent-contract-release.schema.json")
    if release_errors:
        print(json.dumps({"status": "FAIL", "errors": release_errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, release)
    print(json.dumps({"status": "PASS", "out": str(args.out.resolve()), "contracts": len(contracts), "releaseHash": canonical_hash(release)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
