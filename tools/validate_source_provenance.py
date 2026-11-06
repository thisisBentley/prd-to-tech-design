#!/usr/bin/env python3
"""Validate artifact provenance and cross-artifact version consistency.

This catches prototype/overview metadata pointing at a different PRD version,
which was one of the failure modes in ZY20250117-779.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_version(text: str, labels: list[str]) -> str | None:
    for label in labels:
        patterns = [
            rf"{re.escape(label)}\s*[:=]\s*[\"']?v?(\d+(?:\.\d+)+)",
            rf"{re.escape(label)}[^>\n]*content\s*=\s*[\"']v?(\d+(?:\.\d+)+)",
            rf"{re.escape(label)}[^>\n]*[\"']v?(\d+(?:\.\d+)+)[\"']",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.I)
            if m:
                return f"v{m.group(1)}"
    return None


def validate(root: Path, prd: Path, prototype: Path | None, overview: Path | None, expected_version: str | None) -> list[str]:
    errors: list[str] = []
    prd_text = prd.read_text(encoding="utf-8", errors="replace")
    version = expected_version or find_version(prd_text, ["当前版本", "prdVersion", "PRD version", "版本"])
    if not version:
        errors.append("cannot determine PRD version")
    if prototype and prototype.exists():
        text = prototype.read_text(encoding="utf-8", errors="replace")
        declared = find_version(text, ["source-prd-version", "sourcePrdVersion", "prdVersion", "PRD version"])
        if declared and version and declared.lower() != version.lower():
            errors.append(f"prototype declares {declared}, expected {version}")
        if not declared:
            errors.append("prototype does not declare source PRD version")
    if overview and overview.exists():
        text = overview.read_text(encoding="utf-8", errors="replace")
        declared = find_version(text, ["source-prd-version", "sourcePrdVersion", "prdVersion", "PRD version"])
        if declared and version and declared.lower() != version.lower():
            errors.append(f"overview declares {declared}, expected {version}")
    elif overview:
        errors.append(f"overview missing: {overview}")

    lock = root / ".delivery" / "ui-pack.lock.json"
    if lock.exists():
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            for key in ["packHash", "standardsHash", "resourceIndexHash"]:
                value = data.get(key)
                if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                    errors.append(f"ui-pack.lock {key} is missing or not sha256")
            for gate in ["u1Gate", "u2Gate"]:
                if not isinstance(data.get(gate), dict) or not data[gate].get("version"):
                    errors.append(f"ui-pack.lock {gate}.version is missing")
        except Exception as exc:
            errors.append(f"invalid ui-pack.lock.json: {exc}")
    else:
        errors.append("missing .delivery/ui-pack.lock.json")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="01-delivery root")
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.prd.resolve(), args.prototype.resolve() if args.prototype else None, args.overview.resolve() if args.overview else None, args.version)
    prd_text = args.prd.read_text(encoding="utf-8", errors="replace")
    version = args.version or find_version(prd_text, ["当前版本", "prdVersion", "PRD version", "版本"])
    result = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "FAIL",
        "prd": str(args.prd.resolve()),
        "prdVersion": version,
        "prdHash": sha256(args.prd.resolve()),
        "prototype": str(args.prototype.resolve()) if args.prototype else None,
        "prototypeHash": sha256(args.prototype.resolve()) if args.prototype and args.prototype.exists() else None,
        "overview": str(args.overview.resolve()) if args.overview else None,
        "overviewHash": sha256(args.overview.resolve()) if args.overview and args.overview.exists() else None,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
