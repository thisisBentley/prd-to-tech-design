#!/usr/bin/env python3
"""Select a specialist tool from execution mode and intent without asking the user to route it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trust_kernel import load, route_specialist_tool, save_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--execution-mode", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = route_specialist_tool(args.workflow_id, args.execution_mode, args.intent, load(args.policy.resolve()), args.policy.resolve())
    save_json(args.out, result)
    print(json.dumps({"status": result["status"], "selectedTool": result.get("selectedTool"), "out": str(args.out.resolve())}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ROUTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
