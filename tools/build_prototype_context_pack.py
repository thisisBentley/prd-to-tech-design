#!/usr/bin/env python3
"""Build the minimum Prototype Context Pack V2 for a scoped patch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prototype_changes import build_context_pack, load, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-model", type=Path, required=True)
    parser.add_argument("--change-set", type=Path, required=True)
    parser.add_argument("--impact-report", type=Path, required=True)
    parser.add_argument("--patch-scope", type=Path, required=True)
    parser.add_argument("--token-budget", type=int, default=4000)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    pack = build_context_pack(
        load(args.current_model.resolve()),
        load(args.change_set.resolve()),
        load(args.impact_report.resolve()),
        load(args.patch_scope.resolve()),
        args.token_budget,
    )
    errors = validate_schema_value(pack, "prototype-context-pack.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, pack)
    status = "PASS" if pack.get("withinTokenBudget", True) else "TOKEN_BUDGET_EXCEEDED"
    print(json.dumps({"status": status, "out": str(args.out.resolve()), "selectedNodes": len(pack["selectedNodes"]), "omittedNodes": len(pack["omittedNodes"]), "estimatedTokens": pack["estimatedTokens"], "tokenBudget": pack["tokenBudget"]}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
