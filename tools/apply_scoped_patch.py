#!/usr/bin/env python3
"""Apply a replacement-only patch and reject any change outside Patch Scope."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prototype_changes import apply_patch, load, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--current-model", type=Path, required=True)
    parser.add_argument("--patch-scope", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--result-out", type=Path, required=True)
    args = parser.parse_args()
    patch = load(args.patch.resolve())
    errors = validate_schema_value(patch, "scoped-patch.schema.json")
    if errors:
        result = {"schemaVersion": 1, "status": "FAIL", "errors": errors, "appliedOperations": 0, "changedCharacters": 0}
        save(args.result_out, result)
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    patched, result = apply_patch(args.prototype, args.current_model, load(args.patch_scope.resolve()), patch)
    if result["status"] == "PASS":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(patched, encoding="utf-8")
    result_errors = validate_schema_value(result, "scoped-patch-result.schema.json")
    if result_errors:
        result["status"] = "FAIL"
        result.setdefault("errors", []).extend(result_errors)
    save(args.result_out, result)
    print(json.dumps({"status": result["status"], "out": str(args.out.resolve()) if result["status"] == "PASS" else None, "beforeHash": result.get("beforeHash"), "afterHash": result.get("afterHash"), "appliedOperations": result.get("appliedOperations"), "changedCharacters": result.get("changedCharacters"), "errors": result.get("errors", [])}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
