#!/usr/bin/env python3
"""Validate a Delivery Operating Procedure snapshot and its source hashes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from delivery_operating_procedure import digest, load
from trust_kernel import validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--procedure", type=Path, required=True)
    parser.add_argument("--verify-source-hashes", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    procedure = load(args.procedure.resolve(), {})
    errors = validate_schema_value(procedure, "delivery-operating-procedure.schema.json")
    if procedure.get("status") == "BLOCKED":
        errors.append("procedure status is BLOCKED")
    if args.verify_source_hashes:
        for item in procedure.get("provenance") or []:
            path = Path(str(item.get("path", "")))
            if not path.is_file():
                errors.append(f"source missing: {path}")
            elif digest(path) != item.get("sha256"):
                errors.append(f"source hash drift: {path}")
    report = {
        "schemaVersion": 1,
        "procedureId": procedure.get("procedureId"),
        "status": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "metrics": procedure.get("metrics", {}),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
