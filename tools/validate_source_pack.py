#!/usr/bin/env python3
"""Validate a Source Pack Registry and enforce D.12 evidence/use boundaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from source_pack import load, validate_registry
from trust_kernel import validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    registry = load(args.registry.resolve())
    errors = validate_schema_value(registry, "source-pack-registry.schema.json")
    errors.extend(validate_registry(registry, args.repo_root.resolve()))
    report = {
        "schemaVersion": 1,
        "packId": registry.get("packId"),
        "status": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "metrics": registry.get("metrics", {}),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
