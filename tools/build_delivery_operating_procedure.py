#!/usr/bin/env python3
"""Build the unified Delivery Operating Procedure from existing contracts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from delivery_operating_procedure import build, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--requirement-id", required=True)
    parser.add_argument("--artifact-profile", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--objective")
    parser.add_argument("--generation-contract", type=Path, required=True)
    parser.add_argument("--policy-lock", type=Path, required=True)
    parser.add_argument("--obligations", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--tool-policy", type=Path, required=True)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--repair-policy", type=Path, required=True)
    parser.add_argument("--source-pack", type=Path, required=True)
    parser.add_argument("--task-domain", default="PRODUCT_ENGINEERING")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = build(
            workflow_id=args.workflow_id,
            requirement_id=args.requirement_id,
            artifact_profile=args.artifact_profile,
            revision=args.revision,
            requirement_path=args.requirement.resolve(),
            objective=args.objective,
            generation_contract_path=args.generation_contract.resolve(),
            policy_lock_path=args.policy_lock.resolve(),
            obligations_path=args.obligations.resolve(),
            plan_path=args.plan.resolve(),
            tool_policy_path=args.tool_policy.resolve(),
            budget_path=args.budget.resolve(),
            repair_policy_path=args.repair_policy.resolve(),
            source_pack_path=args.source_pack.resolve(),
            task_domain=args.task_domain,
        )
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), payload)
    print(json.dumps({
        "status": payload["status"],
        "procedureId": payload["procedureId"],
        "subgoals": payload["metrics"]["subgoals"],
        "toolRoutes": payload["metrics"]["toolRoutes"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
