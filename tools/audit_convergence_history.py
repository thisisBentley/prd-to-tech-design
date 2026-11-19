#!/usr/bin/env python3
"""Replay adjacent Finding snapshots for forensic convergence auditing only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_convergence import evaluate_convergence, load, now, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, nargs="+", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--invariant-registry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    snapshots = [load(path.resolve()) for path in args.snapshots]
    if len(snapshots) < 2:
        raise SystemExit("at least two snapshots are required")
    policy = load(args.policy.resolve())
    registry = load(args.invariant_registry.resolve())
    transitions = []
    for index in range(1, len(snapshots)):
        transition = evaluate_convergence(
            snapshots[index - 1],
            snapshots[index],
            policy,
            registry,
            history=snapshots[: index + 1],
            enforce_revision_binding=False,
        )
        transitions.append({
            "fromRevision": str(snapshots[index - 1].get("revision")),
            "toRevision": str(snapshots[index].get("revision")),
            "status": transition["status"],
            "metrics": transition["metrics"],
            "checks": transition["checks"],
            "blockingReasons": transition["blockingReasons"],
        })
    report = {
        "schemaVersion": 1,
        "mode": "HISTORICAL_FORENSIC_ONLY",
        "workflowId": str(snapshots[0].get("workflowId", "unknown")),
        "closureEligible": False,
        "transitionCount": len(transitions),
        "blockedTransitions": sum(1 for item in transitions if item["status"] == "BLOCKED"),
        "repeatedRootCauses": sorted({
            item["rootCauseId"]
            for transition in transitions
            for item in transition["metrics"]["repeatedRootCauses"]
        }),
        "transitions": transitions,
        "checkedAt": now(),
    }
    save(args.out, report)
    print(json.dumps({
        "mode": report["mode"],
        "closureEligible": report["closureEligible"],
        "transitionCount": report["transitionCount"],
        "blockedTransitions": report["blockedTransitions"],
        "repeatedRootCauses": report["repeatedRootCauses"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
