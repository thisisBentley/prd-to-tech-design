#!/usr/bin/env python3
"""Create a deterministic Artifact Pair binding PRD, Prototype and optional Overview."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--artifact-profile", choices=["PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"], required=True)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--prd-revision", required=True)
    parser.add_argument("--prototype-revision", required=True)
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--overview-revision")
    parser.add_argument("--last-prototype-delta-id")
    parser.add_argument("--last-prd-reconciliation-id")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prd = args.prd.resolve(); prototype = args.prototype.resolve()
    if not prd.exists() or not prototype.exists():
        raise SystemExit("PRD and Prototype files must exist")
    if args.overview and not args.overview.exists():
        raise SystemExit("Overview file must exist when supplied")
    pair_status = "SYNCED"
    if args.prd_revision != args.prototype_revision:
        pair_status = "RESYNC_REQUIRED"
    elif args.overview and args.overview_revision != args.prd_revision:
        pair_status = "STALE"
    payload = {
        "schemaVersion": 1,
        "pairId": "artifact-pair-" + secrets.token_hex(4),
        "workflowId": args.workflow_id,
        "artifactProfile": args.artifact_profile,
        "prdRevision": args.prd_revision,
        "prototypeRevision": args.prototype_revision,
        "pairStatus": pair_status,
        "prdPath": str(prd),
        "prdHash": digest(prd),
        "prototypePath": str(prototype),
        "prototypeHash": digest(prototype),
        "authorityMatrix": {"businessDomain": "PRD", "interactionDomain": "PROTOTYPE", "conflictPolicy": "RESYNC_REQUIRED"},
        "sourceDomains": ["PRD", "PROTOTYPE"] + (["OVERVIEW"] if args.overview else []),
        "createdAt": now(),
        "updatedAt": now(),
    }
    if args.overview:
        overview = args.overview.resolve()
        payload.update({
            "overviewRevision": args.overview_revision or args.prd_revision,
            "overviewPath": str(overview),
            "overviewHash": digest(overview),
        })
    if args.last_prototype_delta_id:
        payload["lastPrototypeDeltaId"] = args.last_prototype_delta_id
    if args.last_prd_reconciliation_id:
        payload["lastPrdReconciliationId"] = args.last_prd_reconciliation_id
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": pair_status, "pair": str(args.out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
