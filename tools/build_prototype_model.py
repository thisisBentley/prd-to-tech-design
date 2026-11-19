#!/usr/bin/env python3
"""Extract a deterministic Prototype Model from standalone HTML."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from interaction_contracts import build_model, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    model = build_model(args.prototype)
    errors = validate_schema_value(model, "prototype-model.schema.json")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    save(args.out, model)
    print(json.dumps({"status": "PASS", "out": str(args.out.resolve()), "metrics": model["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
