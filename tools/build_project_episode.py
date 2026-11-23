#!/usr/bin/env python3
"""Build a Project Episode from completed Delivery evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_episode import build, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--requirement-id", required=True)
    parser.add_argument("--artifact-profile", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--procedure", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--finding-ledger", type=Path, required=True)
    parser.add_argument("--repair-cycle", type=Path, required=True)
    parser.add_argument("--cost-ledger", type=Path, required=True)
    parser.add_argument("--final-gate", type=Path, required=True)
    parser.add_argument("--consumer-report", type=Path, action="append", default=[])
    parser.add_argument("--decision-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = build(
            run_root=args.run_root.resolve(),
            workflow_id=args.workflow_id,
            requirement_id=args.requirement_id,
            artifact_profile=args.artifact_profile,
            revision=args.revision,
            procedure_path=args.procedure.resolve(),
            handoff_path=args.handoff.resolve(),
            finding_ledger_path=args.finding_ledger.resolve(),
            repair_cycle_path=args.repair_cycle.resolve(),
            cost_ledger_path=args.cost_ledger.resolve(),
            final_gate_path=args.final_gate.resolve(),
            consumer_report_paths=[path.resolve() for path in args.consumer_report],
            decision_dir=args.decision_dir.resolve(),
        )
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), payload)
    print(json.dumps({
        "status": payload["status"],
        "episodeId": payload["episodeId"],
        "revision": payload["revision"],
        "timelineEvents": payload["metrics"]["timelineEvents"],
        "trainingEligible": payload["trainingEligibility"]["eligible"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
