#!/usr/bin/env python3
"""Synthesize Query Results into Research Records, TECH gaps and Decision Cards."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_agent_contracts import validate_decision, validate_research_record

AVAILABLE = {"CONFIRMED", "CURRENT_MAINLINE", "HISTORICAL_ONLY"}
PRODUCT_TYPES = {"BUSINESS_POLICY", "PERMISSION", "TERMINOLOGY"}
TECH_TYPES = {"TECHNICAL_IMPLEMENTATION"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def owner_for(clue: dict[str, Any]) -> str:
    if clue.get("resolutionOwner"):
        return str(clue["resolutionOwner"])
    if clue.get("clueType") in PRODUCT_TYPES and clue.get("decisionQuestion") and clue.get("decisionOptions"):
        return "PRODUCT"
    if clue.get("clueType") in TECH_TYPES:
        return "TECH"
    return "DELIVERY"


def safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned or "research"


def synthesize(request: dict[str, Any], query_result: dict[str, Any], run_root: Path) -> dict[str, Any]:
    workflow_id = request["workflowId"]
    records_dir = run_root / ".agents" / "research" / "records"
    decisions_dir = run_root / ".agents" / "decisions"
    records_dir.mkdir(parents=True, exist_ok=True)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    by_clue: dict[str, list[dict[str, Any]]] = {}
    for item in query_result.get("records", []):
        by_clue.setdefault(str(item.get("clueId")), []).append(item)
    record_index: list[dict[str, Any]] = []
    decision_index: list[str] = []
    technical_gaps: list[dict[str, Any]] = []
    errors: list[str] = []
    created_at = datetime.now(timezone.utc).isoformat()
    for clue in request.get("clues", []):
        clue_id = str(clue["clueId"])
        items = by_clue.get(clue_id, [])
        available = [item for item in items if item.get("status") in AVAILABLE and item.get("claims") and item.get("evidenceRefs")]
        conflicts = [item for item in items if item.get("status") == "CONFLICTING" and item.get("evidenceRefs")]
        owner = owner_for(clue)
        evidence_refs = sorted({ref for item in available + conflicts for ref in item.get("evidenceRefs", [])})
        if available and not conflicts:
            verdict = "FACT_RESOLVED"
            decision_required = False
            findings = []
            for item in available:
                for claim in item.get("claims", []):
                    text = claim.get("claim") if isinstance(claim, dict) else str(claim)
                    if text:
                        findings.append({"claim": text, "evidenceRefs": item.get("evidenceRefs", []), "confidence": claim.get("confidence", "MEDIUM") if isinstance(claim, dict) else "MEDIUM"})
            if not findings:
                verdict = "NO_EVIDENCE"
                decision_required = owner == "PRODUCT" and bool(clue.get("decisionQuestion") and clue.get("decisionOptions"))
        elif conflicts:
            verdict = "FACT_CONFLICT"
            decision_required = owner == "PRODUCT" and bool(clue.get("decisionQuestion") and clue.get("decisionOptions"))
            findings = [{"claim": f"conflicting evidence from {item.get('queryId')}: {item.get('sourceRef')}", "evidenceRefs": item.get("evidenceRefs", []), "confidence": "MEDIUM"} for item in conflicts]
        else:
            verdict = "NO_EVIDENCE"
            decision_required = owner == "PRODUCT" and bool(clue.get("decisionQuestion") and clue.get("decisionOptions"))
            findings = [{"claim": f"No usable evidence returned for query {item.get('queryId')}", "evidenceRefs": item.get("evidenceRefs", [""]), "confidence": "LOW"} for item in items if item.get("status") == "UNAVAILABLE"] or [{"claim": "No evidence returned for this clue", "evidenceRefs": [str(run_root / ".agents" / "research" / "query-result.json")], "confidence": "LOW"}]
        record = {
            "schemaVersion": 1,
            "researchId": f"RS-{safe_id(clue_id)}",
            "workflowId": workflow_id,
            "clue": clue["clue"],
            "clueType": clue["clueType"],
            "researchPlan": [{"source": query["source"], "query": query["query"], "purpose": query["purpose"]} for query in clue.get("queries", [])],
            "sourcesChecked": [{"source": item.get("source", "UNKNOWN"), "status": "AVAILABLE" if item.get("status") in AVAILABLE else "UNAVAILABLE", "evidenceRefs": item.get("evidenceRefs", [])} for item in items],
            "findings": findings,
            "verdict": verdict,
            "decisionRequired": decision_required,
            "resolutionOwner": owner,
            "decisionRationale": f"Resolution owner is {owner}; business decision is required only when the remaining outcome changes user-visible behavior." if verdict != "FACT_RESOLVED" else "The available evidence uniquely resolves this factual clue.",
            "nextAction": "Write the resolved fact into PRD/Capability Context." if verdict == "FACT_RESOLVED" else ("Resolve through a product Decision Card." if owner == "PRODUCT" and decision_required else "Resolve technical/delivery gap before proceeding."),
            "evidenceRefs": evidence_refs or [str(run_root / ".agents" / "research" / "query-result.json")],
            "createdAt": created_at,
        }
        errors.extend(validate_research_record(record, str(records_dir / f"{record['researchId']}.json")))
        save(records_dir / f"{record['researchId']}.json", record)
        record_index.append({"researchId": record["researchId"], "path": str((records_dir / f"{record['researchId']}.json").resolve()), "verdict": verdict, "resolutionOwner": owner})
        if owner == "TECH" and verdict in {"NO_EVIDENCE", "FACT_CONFLICT"}:
            technical_gaps.append({"researchId": record["researchId"], "clue": clue["clue"], "nextAction": record["nextAction"], "evidenceRefs": record["evidenceRefs"]})
        if decision_required and owner == "PRODUCT":
            options = clue.get("decisionOptions", [])
            card = {
                "schemaVersion": 1,
                "decisionId": f"RD-{safe_id(clue_id)}",
                "workflowId": workflow_id,
                "reviewerRole": "semantic-consistency-reviewer",
                "businessScenario": clue["clue"],
                "currentFacts": [claim["claim"] for claim in findings] or ["No decisive fact is available."],
                "ambiguity": clue.get("decisionQuestion", clue["clue"]),
                "options": options,
                "recommendation": options[0]["label"],
                "defaultAndRisk": "No automatic product default is applied; the requirement remains blocked until the owner selects an option.",
                "owner": "Product Owner",
                "closeCondition": "Product selects one option and the PRD is resynchronized.",
                "researchRecordPath": f"../research/records/{record['researchId']}.json",
                "researchVerdict": "NEEDS_BUSINESS_DECISION",
                "researchEvidenceRefs": record["evidenceRefs"],
                "whyDecisionRequired": "The remaining choice changes user-visible behavior and available facts do not determine one outcome.",
                "status": "open",
                "createdAt": created_at,
            }
            errors.extend(validate_decision(card, str(decisions_dir / f"{card['decisionId']}.json")))
            save(decisions_dir / f"{card['decisionId']}.json", card)
            decision_index.append(str((decisions_dir / f"{card['decisionId']}.json").resolve()))
    index = {"schemaVersion": 1, "workflowId": workflow_id, "records": record_index, "decisionCards": decision_index, "technicalGaps": technical_gaps, "generatedAt": created_at}
    save(run_root / ".agents" / "research" / "index.json", index)
    save(run_root / ".agents" / "context" / "technical-gaps.json", {"schemaVersion": 1, "workflowId": workflow_id, "gaps": technical_gaps})
    summary = {"schemaVersion": 1, "status": "PASS" if not errors else "BLOCKED", "workflowId": workflow_id, "researchRecords": len(record_index), "decisionCards": len(decision_index), "technicalGaps": len(technical_gaps), "errors": errors, "checkedAt": created_at}
    save(run_root / ".agents" / "research" / "synthesis-result.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--query-result", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = synthesize(load(args.request.resolve()), load(args.query_result.resolve()), args.run_root.resolve())
    if args.out:
        save(args.out.resolve(), summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
