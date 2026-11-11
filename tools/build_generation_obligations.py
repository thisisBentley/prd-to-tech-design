#!/usr/bin/env python3
"""Turn an applicable policy lock into frozen producer obligations."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / "references" / "gate-policy-current.json"
if not DEFAULT_PACK.exists():
    DEFAULT_PACK = ROOT / "core" / "gate-policy-current.json"

ARTIFACTS = {
    "REPAIR_PRD": "PRD_DELIVERY.md",
    "REPAIR_PROTOTYPE": "Prototype + Prototype Manifest",
    "REPAIR_OVERVIEW": "Overview.html",
    "REPAIR_JIRA": "Jira_Description.md",
    "REPAIR_EVIDENCE": "Delivery evidence bundle",
    "MANUAL_DECISION": "Decision Context",
    "INCOMPLETE": "Delivery evidence bundle",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-lock", type=Path, required=True)
    parser.add_argument("--policy-pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lock_path = args.policy_lock.resolve()
    pack_path = args.policy_pack.resolve()
    lock = load(lock_path)
    pack = load(pack_path)
    pack_by_id = {item["ruleId"]: item for item in pack.get("rules", [])}
    obligations: list[dict[str, Any]] = []
    for gate in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]:
        for rule_id in (lock.get("applicableRules") or {}).get(gate, []):
            rule = pack_by_id.get(rule_id)
            if rule is None:
                print(json.dumps({"status": "BLOCKED", "error": f"rule missing from policy pack: {rule_id}"}, ensure_ascii=False))
                return 1
            declaration_required = rule["failureAction"] in {"REPAIR_PRD", "REPAIR_PROTOTYPE", "REPAIR_OVERVIEW", "REPAIR_JIRA"}
            obligations.append({
                "obligationId": f"OBL-{rule_id}",
                "ruleId": rule_id,
                "gate": gate,
                "ownerRole": rule["owner"],
                "artifact": ARTIFACTS.get(rule["failureAction"], "Delivery artifact"),
                "title": rule["title"],
                "requiredEvidence": rule["requiredEvidence"],
                "passCondition": rule["passCondition"],
                "failureAction": rule["failureAction"],
                "declarationRequired": declaration_required,
                "status": "OPEN",
                "sourceRef": f"policy://{pack['policyPackId']}/{rule_id}",
            })
    payload = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "targetRevision": args.revision,
        "policyLockPath": str(lock_path),
        "policyLockSha256": digest(lock_path),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "obligations": obligations,
        "metrics": {"total": len(obligations), "open": len(obligations)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "obligations": len(obligations), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
