#!/usr/bin/env python3
"""Build a deterministic Delivery Producer/Reviewer/Repair task DAG."""
from __future__ import annotations
import argparse, json, secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROTOTYPE_PROFILES = {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def task(task_id: str, role: str, kind: str, dependencies: list[str], read_scope: list[str], write_scope: list[str], outputs: list[str], required: bool = True) -> dict[str, Any]:
    return {
        "taskId": task_id,
        "role": role,
        "kind": kind,
        "dependencies": dependencies,
        "readScope": read_scope,
        "writeScope": write_scope,
        "expectedOutputs": outputs,
        "required": required,
        "status": "PENDING",
    }


def build(state: dict[str, Any], iteration: str) -> dict[str, Any]:
    profile = state.get("artifactProfile", "UNKNOWN")
    root = ["01-delivery", ".delivery", "Decision Context"]
    tasks = [
        task("DECISION-READINESS", "decision-readiness-agent", "decision", [], ["Discovery Handoff", "Decision Context"], ["01-delivery/.delivery/decision-context.json"], ["Decision Context READY"]),
        task("PRD-PRODUCE", "prd-producer", "producer", ["DECISION-READINESS"], root, ["01-delivery/*_PRD_DELIVERY.md"], ["PRD candidate"]),
        task("DELIVERY-REVIEW", "delivery-reviewer", "reviewer", ["PRD-PRODUCE"], ["01-delivery/*_PRD_DELIVERY.md", "Decision Context"], [".agents/reviews"], ["Delivery Review Result"]),
        task("QA-RED-TEAM", "qa-red-team", "reviewer", ["PRD-PRODUCE"], ["01-delivery/*_PRD_DELIVERY.md", "Decision Context"], [".agents/reviews"], ["QA Review Result"]),
        task("TECH-PRD-DIAGNOSIS", "tech-prd-diagnostician", "reviewer", ["PRD-PRODUCE"], ["01-delivery/*_PRD_DELIVERY.md", "Decision Context"], [".agents/reviews"], ["Technical PRD Diagnosis"]),
        task("SEMANTIC-CONSISTENCY-REVIEW", "semantic-consistency-reviewer", "reviewer", ["PRD-PRODUCE"], ["01-delivery/*_PRD_DELIVERY.md", "Decision Context", "Capability Context", "Source Provenance"], [".agents/reviews"], ["Semantic Consistency Review"]),
    ]
    last_core = ["DELIVERY-REVIEW", "QA-RED-TEAM", "TECH-PRD-DIAGNOSIS", "SEMANTIC-CONSISTENCY-REVIEW"]
    if profile in PROTOTYPE_PROFILES:
        tasks += [
            task("PROTOTYPE-PRODUCE", "prototype-producer", "producer", ["PRD-PRODUCE"], ["01-delivery/*_PRD_DELIVERY.md", "Decision Context", "Artifact Profile"], ["01-delivery/*_Prototype.html"], ["Prototype candidate"]),
            task("PROTOTYPE-CONTRACT", "prototype-contract-reviewer", "reviewer", ["PROTOTYPE-PRODUCE"] + last_core, ["PRD", "Prototype", "requirements.json"], [".delivery/preflight"], ["Prototype Contract Preflight"]),
            task("RUNTIME-VERIFY", "runtime-verifier", "verification", ["PROTOTYPE-CONTRACT"], ["Prototype", "Runtime Contract"], [".delivery/preflight"], ["Runtime Evidence"]),
        ]
        projection_deps = last_core + ["RUNTIME-VERIFY"]
    else:
        tasks.append(task("UI-BOUNDARY", "ui-boundary-agent", "producer", ["PRD-PRODUCE"] + last_core, ["PRD", "Decision Context"], ["01-delivery/.delivery/ui-boundary-contract.json"], ["UI Boundary Contract"], required=profile == "EXTERNAL_UI_BOUNDARY"))
        projection_deps = last_core + ["UI-BOUNDARY"]
    tasks += [
        task("OVERVIEW-PRODUCE", "overview-producer", "producer", projection_deps, ["PRD", "Prototype", "UI Boundary Contract"], ["01-delivery/*_Overview.html"], ["Overview candidate"]),
        task("PROJECTION-REVIEW", "final-package-reviewer", "reviewer", ["OVERVIEW-PRODUCE"], ["PRD", "Prototype", "Overview", "requirements.json"], [".agents/reviews"], ["Final Package Review"]),
        task("FINDING-CONSOLIDATE", "finding-aggregator", "repair", ["PROJECTION-REVIEW"], [".agents/reviews"], [".agents/repair-batches"], ["Repair Batch"]),
        task("DELIVERY-GATEKEEPER", "deterministic-gatekeeper", "gatekeeper", ["FINDING-CONSOLIDATE"], ["all frozen artifacts", "all review results", "repair batch"], [".agents/reviews"], ["Delivery Ready / Blocked"]),
    ]
    return {
        "schemaVersion": 1,
        "planId": f"delivery-plan-{secrets.token_hex(4)}",
        "workflowId": state["workflowId"],
        "requirementId": (state.get("requirement") or {}).get("id") or "",
        "artifactProfile": profile,
        "iteration": iteration,
        "tasks": tasks,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--iteration", default="r1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    state = load(args.run_root.resolve() / ".agents" / "orchestration.json")
    result = build(state, args.iteration)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "plan": str(args.out), "tasks": len(result["tasks"]), "artifactProfile": result["artifactProfile"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
