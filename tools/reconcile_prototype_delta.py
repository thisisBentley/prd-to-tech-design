#!/usr/bin/env python3
"""Create a PRD reconciliation result from a Prototype Delta."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--from-prd-revision", required=True)
    parser.add_argument("--to-prd-revision", required=True)
    parser.add_argument("--status", choices=["SYNCED", "UNRESOLVED"], default="UNRESOLVED")
    parser.add_argument("--reason", default="PRD has not yet been reconciled with the Prototype Delta.")
    parser.add_argument("--apply", action="store_true", help="Remove deleted-element FR/AC/UI references from the PRD")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    delta = load(args.delta)
    prd_text = args.prd.read_text(encoding="utf-8")
    features, acs, unresolved = [], [], []
    delete_changes = [change for change in delta.get("changes", []) if change.get("action") in {"DELETE", "MOVE"}]
    if args.apply:
        targets = set()
        ui_targets = set()
        for change in delete_changes:
            targets.update(change.get("linkedFeatureIds", []))
            targets.update(change.get("linkedAcIds", []))
            ui_targets.add(change.get("uiElementId", ""))
        kept = []
        for line in prd_text.splitlines():
            references_target = any(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(target)}(?![A-Za-z0-9_-])", line) for target in targets if target)
            references_ui = any(ui and ui in line for ui in ui_targets)
            if references_target or references_ui:
                continue
            kept.append(line)
        prd_text = "\n".join(kept).rstrip() + "\n"
        args.prd.write_text(prd_text, encoding="utf-8")
    remaining_targets = []
    for change in delete_changes:
        remaining_targets.extend([item for item in change.get("linkedFeatureIds", []) if item in prd_text])
        remaining_targets.extend([item for item in change.get("linkedAcIds", []) if item in prd_text])
    effective_status = "SYNCED" if args.status == "SYNCED" and not remaining_targets else "UNRESOLVED"
    for change in delete_changes:
        if effective_status == "SYNCED":
            for fr_id in change.get("linkedFeatureIds", []):
                features.append({"frId": fr_id, "action": "DELETE"})
            for ac_id in change.get("linkedAcIds", []):
                acs.append({"acId": ac_id, "action": "DELETE"})
        else:
            unresolved.append({
                "deltaId": delta["deltaId"],
                "uiElementId": change["uiElementId"],
                "reason": args.reason if not remaining_targets else f"PRD still contains: {', '.join(sorted(set(remaining_targets)))}",
            })
    result = {
        "schemaVersion": 1,
        "reconciliationId": "reconciliation-" + secrets.token_hex(4),
        "workflowId": delta["workflowId"],
        "sourcePrototypeDeltaId": delta["deltaId"],
        "fromPrdRevision": args.from_prd_revision,
        "toPrdRevision": args.to_prd_revision,
        "status": effective_status,
        "updatedFeatures": features,
        "updatedAcceptanceCriteria": acs,
        "unresolvedDeltas": unresolved,
        "evidenceRefs": [str(args.delta.resolve()), str(args.prd.resolve())],
        "prdSha256": hashlib.sha256(args.prd.read_bytes()).hexdigest(),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
