#!/usr/bin/env python3
"""Generate a Prototype Delta from two Prototype Manifests."""
from __future__ import annotations

import argparse
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def element_signature(element: dict) -> tuple:
    return (
        tuple(element.get("frIds", [])),
        tuple(element.get("acIds", [])),
        element.get("visibleLabel", ""),
        tuple(element.get("states", [])),
        element.get("action", ""),
        tuple(element.get("permissions", [])),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--workflow-id")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    previous = load(args.previous); current = load(args.current)
    old = {item["uiElementId"]: item for item in previous.get("elements", [])}
    new = {item["uiElementId"]: item for item in current.get("elements", [])}
    old_order = {item["uiElementId"]: index for index, item in enumerate(previous.get("elements", []))}
    new_order = {item["uiElementId"]: index for index, item in enumerate(current.get("elements", []))}
    changes = []
    semantic = False
    for ui_id in sorted(set(new) - set(old)):
        item = new[ui_id]
        changes.append({
            "action": "ADD",
            "uiElementId": ui_id,
            "linkedFeatureIds": item.get("frIds", []),
            "linkedAcIds": item.get("acIds", []),
            "reason": "Element added in the new Prototype revision.",
            "evidenceRefs": [str(args.current.resolve())],
        })
        semantic = True
    for ui_id in sorted(set(old) - set(new)):
        item = old[ui_id]
        changes.append({
            "action": "DELETE",
            "uiElementId": ui_id,
            "linkedFeatureIds": item.get("frIds", []),
            "linkedAcIds": item.get("acIds", []),
            "reason": "Element was removed from the Prototype.",
            "evidenceRefs": [str(args.previous.resolve()), str(args.current.resolve())],
        })
        semantic = True
    for ui_id in sorted(set(old) & set(new)):
        before = old[ui_id]; after = new[ui_id]
        if element_signature(before) != element_signature(after):
            before_non_copy = (before.get("frIds", []), before.get("acIds", []), before.get("states", []), before.get("action", ""), before.get("permissions", []))
            after_non_copy = (after.get("frIds", []), after.get("acIds", []), after.get("states", []), after.get("action", ""), after.get("permissions", []))
            action = "COPY_CHANGE" if before.get("visibleLabel") != after.get("visibleLabel") and before_non_copy == after_non_copy else "MODIFY"
            changes.append({
                "action": action,
                "uiElementId": ui_id,
                "linkedFeatureIds": sorted(set(before.get("frIds", [])) | set(after.get("frIds", []))),
                "linkedAcIds": sorted(set(before.get("acIds", [])) | set(after.get("acIds", []))),
                "reason": "Element semantics changed between Prototype revisions.",
                "evidenceRefs": [str(args.previous.resolve()), str(args.current.resolve())],
            })
            semantic = True
        elif old_order[ui_id] != new_order[ui_id]:
            changes.append({
                "action": "MOVE",
                "uiElementId": ui_id,
                "linkedFeatureIds": after.get("frIds", []),
                "linkedAcIds": after.get("acIds", []),
                "reason": "Element order changed between Prototype revisions.",
                "evidenceRefs": [str(args.previous.resolve()), str(args.current.resolve())],
            })
            semantic = True
    if not changes:
        changes.append({
            "action": "MODIFY",
            "uiElementId": next(iter(new)) if new else "UI-unknown",
            "reason": "No semantic change detected; manifest revision only.",
            "evidenceRefs": [str(args.current.resolve())],
        })
    result = {
        "schemaVersion": 1,
        "deltaId": "prototype-delta-" + secrets.token_hex(4),
        "workflowId": args.workflow_id or current.get("workflowId", previous.get("workflowId", "unknown")),
        "fromPrototypeRevision": previous.get("prototypeRevision", "unknown"),
        "toPrototypeRevision": current.get("prototypeRevision", "unknown"),
        "changeType": "SEMANTIC" if semantic else "COSMETIC",
        "requiresPrdReconciliation": semantic,
        "changes": changes,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "changeType": result["changeType"], "changes": len(changes), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
