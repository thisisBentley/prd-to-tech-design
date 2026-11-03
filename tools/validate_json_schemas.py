#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

def main() -> int:
    root = Path(__file__).resolve().parents[1] / "schemas"
    failed = False
    for path in sorted(root.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
            print(f"OK {path.name}")
        except Exception as exc:
            failed = True
            print(f"FAIL {path.name}: {exc}")
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
