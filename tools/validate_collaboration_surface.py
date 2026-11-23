#!/usr/bin/env python3
"""Validate a Collaboration Surface and its source hashes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from collaboration_surface import digest, load
from trust_kernel import validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", type=Path, required=True)
    parser.add_argument("--verify-source-hashes", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    surface = load(args.surface.resolve(), {})
    errors = validate_schema_value(surface, "collaboration-surface.schema.json")
    authority = surface.get("authority") or {}
    if authority.get("readOnly") is not True:
        errors.append("collaboration surface must be read-only")
    if authority.get("gateAuthority") != "UNCHANGED":
        errors.append("collaboration surface cannot change gate authority")
    if authority.get("trainingAuthority") != "NONE":
        errors.append("collaboration surface cannot grant training authority")
    if args.verify_source_hashes:
        for item in surface.get("sourceRefs") or []:
            path = Path(str(item.get("path", "")))
            if not path.is_file():
                errors.append(f"source missing: {path}")
            elif digest(path) != item.get("sha256"):
                errors.append(f"source hash drift: {path}")
    report = {
        "schemaVersion": 1,
        "surfaceId": surface.get("surfaceId"),
        "status": "PASS" if not errors else "BLOCKED",
        "surfaceStatus": surface.get("status"),
        "errors": errors,
        "metrics": surface.get("metrics", {}),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
