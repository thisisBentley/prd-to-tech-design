#!/usr/bin/env python3
"""Export isolated review jobs from a Delivery semantic model."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(unit: dict[str, Any]) -> dict[str, Any]:
    return {key: unit.get(key) for key in ("unitId", "kind", "title", "statement", "authority", "frIds", "acIds", "dependencies")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    model_path = args.model.resolve()
    model = load(model_path)
    out_dir = args.out_dir.resolve()
    jobs_dir = out_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    units = model.get("units", [])
    edges = model.get("edges", [])
    contracts = model.get("globalContracts", [])
    unit_by_id = {unit["unitId"]: unit for unit in units}
    contract_by_id = {item["contractId"]: item for item in contracts}

    def related_edges(unit_ids: set[str]) -> list[dict[str, Any]]:
        return [edge for edge in edges if edge.get("fromUnitId") in unit_ids or edge.get("toUnitId") in unit_ids]

    def write_job(job_id: str, layer: str, objective: str, input_ids: list[str], context: dict[str, Any], questions: list[str]) -> dict[str, Any]:
        payload = {
            "schemaVersion": 1,
            "jobId": job_id,
            "workflowId": model["workflowId"],
            "targetRevision": model["targetRevision"],
            "layer": layer,
            "objective": objective,
            "inputUnitIds": sorted(set(input_ids)),
            "context": context,
            "reviewQuestions": questions,
            "outputContract": {
                "schema": "review-result.schema.json",
                "verdicts": ["ACCEPTED", "ACCEPTED_WITH_ACTIONS", "RETURNED", "BLOCKED", "INCOMPLETE"],
                "rule": "Read only the frozen job context. Return one review-result JSON. Any semantic contradiction, hidden assumption, unclosed edge or missing evidence is a finding. Never infer a new business fact.",
            },
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        path = jobs_dir / f"{job_id}.json"
        save(path, payload)
        return {"jobId": job_id, "path": str(path), "sha256": digest(path), "layer": layer, "inputUnitIds": payload["inputUnitIds"]}

    manifest_jobs: list[dict[str, Any]] = []
    manifest_jobs.append(write_job(
        "GLOBAL-CONTRACTS", "CONTRACT", "Verify that global contracts are unique, coherent and authoritative.",
        [item["contractId"] for item in contracts],
        {"artifactProfile": model.get("artifactProfile"), "globalContracts": contracts, "unitCounts": model.get("metrics")},
        ["Does any global contract duplicate or contradict another contract?", "Is each contract specific enough to govern dependent feature slices?", "Are terminology, permissions, states, enums and capability reuse internally coherent?"],
    ))

    for unit in units:
        if unit.get("kind") != "FEATURE_SLICE":
            continue
        unit_id = unit["unitId"]
        linked_acs = [item for item in units if unit_id in item.get("frIds", []) and item.get("kind") == "ACCEPTANCE_CRITERION"]
        linked_ui = [item for item in units if unit_id in item.get("frIds", []) and item.get("kind") == "INTERACTION_CONTRACT"]
        dependencies = [contract_by_id[item] for item in unit.get("dependencies", []) if item in contract_by_id]
        context_units = [summary(unit)] + [summary(item) for item in linked_acs + linked_ui]
        manifest_jobs.append(write_job(
            f"LOCAL-{unit_id}", "LOCAL", f"Verify semantic closure of feature slice {unit_id}.",
            [unit_id] + [item["unitId"] for item in linked_acs + linked_ui] + [item["contractId"] for item in dependencies],
            {"feature": unit, "globalContracts": dependencies, "acceptanceCriteria": linked_acs, "interactionContracts": linked_ui, "relatedEdges": related_edges({unit_id} | {item['unitId'] for item in linked_acs + linked_ui}), "unitSummaries": context_units},
            ["Does the feature form one closed trigger-action-result-recovery loop?", "Do all rules have authority and evidence?", "Are permission and state assumptions consistent with global contracts?", "Does every UI-visible claim map to an interaction contract?", "Can two competent engineers infer the same user result?"],
        ))

    for unit in units:
        if unit.get("kind") != "JOURNEY":
            continue
        unit_id = unit["unitId"]
        features = [unit_by_id[item] for item in unit.get("frIds", []) if item in unit_by_id]
        acs = [item for item in units if item.get("kind") == "ACCEPTANCE_CRITERION" and set(item.get("frIds", [])) & set(unit.get("frIds", []))]
        manifest_jobs.append(write_job(
            f"JOURNEY-{unit_id}", "EDGE", f"Verify cross-feature semantic continuity of journey {unit_id}.",
            [unit_id] + [item["unitId"] for item in features + acs],
            {"journey": unit, "features": [summary(item) for item in features], "acceptanceCriteria": [summary(item) for item in acs], "relatedEdges": related_edges({unit_id} | {item['unitId'] for item in features + acs})},
            ["Does the journey satisfy its declared goal without gaps?", "Do state, permission and result semantics stay consistent across the referenced features?", "Are hand-offs and user-visible transitions described without hidden assumptions?"],
        ))

    manifest_jobs.append(write_job(
        "EDGE-REVIEW", "EDGE", "Challenge all explicit cross-unit edges for semantic validity.",
        sorted({edge["fromUnitId"] for edge in edges} | {edge["toUnitId"] for edge in edges}),
        {"edges": edges, "units": [summary(unit) for unit in units], "globalContracts": contracts},
        ["Does each DEPENDS_ON edge point to the correct authority?", "Does each VERIFIED_BY edge cover the full claimed behavior?", "Does each BINDS_UI edge preserve roles, states, feedback and context?", "Does each COVERS journey edge cover the goal without omission?", "Are any edges semantically wrong even though structurally present?"],
    ))

    manifest_jobs.append(write_job(
        "GLOBAL-INTEGRATION", "GLOBAL", "Challenge the integrated model for contradictions, omissions and false closure.",
        sorted(unit_by_id),
        {"metrics": model.get("metrics"), "globalContracts": [summary(item) | {"kind": item.get("kind")} for item in contracts], "features": [summary(unit) for unit in units if unit.get("kind") == "FEATURE_SLICE"], "acceptanceCriteria": [summary(unit) for unit in units if unit.get("kind") == "ACCEPTANCE_CRITERION"], "journeys": [summary(unit) for unit in units if unit.get("kind") == "JOURNEY"], "interactionContracts": [summary(unit) for unit in units if unit.get("kind") == "INTERACTION_CONTRACT"], "edgeCounts": {relation: sum(1 for edge in edges if edge.get("relation") == relation) for relation in sorted({edge.get("relation") for edge in edges})}},
        ["Do the local units compose into one coherent product contract?", "Is every AC independently verifiable from the declared sources?", "Is there any orphan goal, orphan rule, orphan AC or duplicate authority?", "Can a downstream tech-design reviewer implement the contract without inventing business facts?", "What would falsify the claim that the package is semantically closed?"],
    ))

    manifest = {
        "schemaVersion": 1,
        "workflowId": model["workflowId"],
        "targetRevision": model["targetRevision"],
        "modelPath": str(model_path),
        "modelSha256": digest(model_path),
        "jobs": manifest_jobs,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    save(out_dir / "job-manifest.json", manifest)
    print(json.dumps({"status": "READY", "jobs": len(manifest_jobs), "out": str(out_dir / 'job-manifest.json')}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
