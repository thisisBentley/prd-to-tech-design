#!/usr/bin/env python3
"""Close a research-backed product Decision Card and emit a resync instruction."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_agent_contracts import validate_decision


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--selected-option", required=True)
    parser.add_argument("--closed-by", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resync-out", type=Path, required=True)
    args = parser.parse_args()
    card = load(args.decision.resolve())
    errors = validate_decision(card, str(args.decision))
    selected = next((item for item in card.get("options", []) if item.get("optionId") == args.selected_option), None)
    if selected is None:
        errors.append(f"selected option not found: {args.selected_option}")
    if card.get("status") not in {"open", "awaiting_confirmation", None}:
        errors.append(f"decision is not open: {card.get('status')}")
    if errors:
        print(json.dumps({"status": "BLOCKED", "errors": errors}, ensure_ascii=False))
        return 1
    closed_at = datetime.now(timezone.utc).isoformat()
    card.update({"status": "confirmed", "selectedOptionId": selected["optionId"], "selectedOptionLabel": selected["label"], "closedBy": args.closed_by, "closedAt": closed_at, "resyncRequired": True})
    save(args.out.resolve(), card)
    resync = {
        "schemaVersion": 1,
        "decisionId": card["decisionId"],
        "workflowId": card["workflowId"],
        "selectedOptionId": selected["optionId"],
        "selectedOptionLabel": selected["label"],
        "requiresPrdResync": True,
        "affectedResearchRecord": card.get("researchRecordPath"),
        "createdAt": closed_at,
    }
    save(args.resync_out.resolve(), resync)
    print(json.dumps({"status": "CONFIRMED", "decisionId": card["decisionId"], "selectedOptionId": selected["optionId"], "out": str(args.out), "resync": str(args.resync_out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
