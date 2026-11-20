#!/usr/bin/env python3
"""Evaluate bounded repair rounds in shadow mode and emit the terminal state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save
from trust_kernel import now, validate_schema_value


def normalized_artifact(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./").strip()


def add_finding(findings: list[dict[str, Any]], code: str, message: str, refs: list[str], round_id: str | None = None) -> None:
    payload = {"code": code, "message": message, "evidenceRefs": refs, "roundId": round_id}
    findings.append({"findingId": "BOUNDED-REPAIR-" + code + "-" + canonical_hash(payload)[:12], **payload})


def evaluate(batch: dict[str, Any], rounds: list[dict[str, Any]], policy: dict[str, Any], batch_path: Path, policy_path: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    batch_errors = validate_schema_value(batch, "change-set-batch.schema.json")
    policy_errors = validate_schema_value(policy, "bounded-repair-policy.schema.json")
    for error in batch_errors:
        add_finding(findings, "CHANGE_SET_BATCH_INVALID", error, [str(batch_path.resolve())])
    for error in policy_errors:
        add_finding(findings, "REPAIR_POLICY_INVALID", error, [str(policy_path.resolve())])
    if findings:
        return run_payload(batch, batch_path, policy, policy_path, [], "BLOCKED", "BLOCKED", findings, [], 0, 0, 0, 0)
    if batch.get("status") != "READY_FOR_REPAIR":
        add_finding(findings, "CHANGE_SET_BATCH_NOT_READY", f"Change Set batch status is {batch.get('status')}.", [str(batch_path.resolve())])
        return run_payload(batch, batch_path, policy, policy_path, [], "BLOCKED", "BLOCKED", findings, [], 0, 0, 0, 0)

    change_sets = {str(item["changeSetId"]): item for item in batch.get("changeSets", [])}
    all_change_set_ids = set(change_sets)
    covered: set[str] = set()
    covered_roots: set[str] = set()
    evaluations: list[dict[str, Any]] = []
    repeated_roots: set[str] = set()
    scope_violations = 0
    independent_failures = 0
    previous_round: dict[str, Any] | None = None
    terminal_state: str | None = None
    terminal_status: str | None = None
    seen_revisions: set[str] = set()
    seen_round_ids: set[str] = set()
    initial_open_blocking = 0

    for position, round_data in enumerate(rounds, start=1):
        round_errors = validate_schema_value(round_data, "bounded-repair-round.schema.json")
        round_id = str(round_data.get("roundId") or f"round-{position}")
        reasons: list[str] = []
        structural_reasons: list[str] = []
        if round_errors:
            reasons.extend(f"schema: {error}" for error in round_errors)
            add_finding(findings, "REPAIR_ROUND_INVALID", "; ".join(round_errors), [str(batch_path.resolve())], round_id)
            terminal_state, terminal_status = "BLOCKED", "BLOCKED"
            evaluations.append(round_evaluation(round_data, round_id, "BLOCKED", reasons, {}))
            break
        verification = round_data["verification"]
        if position == 1:
            initial_open_blocking = int(verification["baselineOpenBlocking"])
        if int(round_data["roundIndex"]) != position:
            structural_reasons.append("roundIndex is not contiguous")
        if round_id in seen_round_ids:
            structural_reasons.append("roundId is duplicated")
        if round_data["revision"] in seen_revisions:
            structural_reasons.append("revision is reused across rounds")
        seen_round_ids.add(round_id)
        seen_revisions.add(round_data["revision"])

        selected_ids = [str(item) for item in round_data["changeSetIds"]]
        unknown_ids = sorted(set(selected_ids) - all_change_set_ids)
        if unknown_ids:
            structural_reasons.append("unknown Change Sets: " + ", ".join(unknown_ids))
        repeated_ids = sorted(set(selected_ids) & covered)
        if repeated_ids:
            structural_reasons.append("Change Sets already covered: " + ", ".join(repeated_ids))
        selected = [change_sets[item] for item in selected_ids if item in change_sets]
        allowed_artifacts = {
            normalized_artifact(str(artifact["path"]))
            for change_set in selected
            for artifact in change_set.get("affectedArtifacts", [])
        }
        changed_artifacts = {normalized_artifact(item) for item in round_data["patch"]["changedArtifacts"]}
        outside = sorted(changed_artifacts - allowed_artifacts)
        if outside:
            scope_violations += 1
            structural_reasons.append("changed artifacts outside Change Set scope: " + ", ".join(outside))
        if round_data["patch"]["status"] != "PASS":
            structural_reasons.append("patch status is not PASS")
        if round_data["patch"]["beforeHash"] == round_data["patch"]["afterHash"]:
            structural_reasons.append("patch did not change the candidate hash")
        if round_data["rebuild"]["status"] != "PASS":
            structural_reasons.append("derived rebuild status is not PASS")
        if not verification["independentContext"] or verification["producerContextId"] == verification["verifierContextId"] or verification["producerRole"] == verification["verifierRole"]:
            independent_failures += 1
            structural_reasons.append("verification is not independent")
        if verification["externalGateStatus"] in {"FAIL", "ENVIRONMENT_BLOCKED"}:
            structural_reasons.append("external gate status indicates failure or environment blockage")
        if round_data["businessRevisionCreated"] and not any(item.get("businessRevisionRequired") for item in selected):
            structural_reasons.append("non-business Change Set created a business revision")
        reasons.extend(structural_reasons)

        if selected:
            covered.update(selected_ids)
            covered_roots.update(str(item["rootCauseId"]) for item in selected)
        open_roots = {str(item) for item in verification["openRootCauseIds"]}
        if previous_round:
            previous_open = {str(item) for item in (previous_round.get("verification") or {}).get("openRootCauseIds", [])}
            repeated_roots.update(previous_open & open_roots)

        baseline_score = float(verification["baselineWeightedScore"])
        current_score = float(verification["weightedScore"])
        baseline_open = int(verification["baselineOpenBlocking"])
        current_open = int(verification["openBlocking"])
        regressed = verification["newBlockingFindings"] > 0 or current_score < baseline_score or current_open > baseline_open
        improved = current_score > baseline_score or current_open < baseline_open or int(verification["closedFindings"]) > 0
        all_selected_closed = all(str(change_set["rootCauseId"]) not in open_roots for change_set in selected)

        if structural_reasons or verification["status"] == "BLOCKED":
            outcome = "BLOCKED"
            terminal_state, terminal_status = "BLOCKED", "BLOCKED"
        elif regressed:
            outcome = "REGRESSED"
            terminal_state, terminal_status = "REGRESSED", "REGRESSED"
        elif repeated_roots:
            outcome = "NO_IMPROVEMENT"
            terminal_state, terminal_status = "STALLED", "STALLED"
            reasons.append("the same root cause remains open across consecutive rounds: " + ", ".join(sorted(repeated_roots)))
        elif not improved:
            outcome = "NO_IMPROVEMENT"
            terminal_state, terminal_status = "STALLED", "STALLED"
            reasons.append("the round produced no score, finding-count or blocking-count improvement")
        elif verification["status"] == "PASS" and current_open == 0 and all_selected_closed and covered == all_change_set_ids:
            outcome = "PASS"
            terminal_state, terminal_status = "READY_FOR_HUMAN_SUBMISSION", "READY_FOR_HUMAN_SUBMISSION"
        elif verification["status"] == "PASS" and current_open == 0 and covered != all_change_set_ids:
            outcome = "IMPROVING"
            reasons.append("verification passed only a subset of Change Sets")
        else:
            outcome = "IMPROVING"
            if position >= int(policy["maxRounds"]):
                terminal_state, terminal_status = "MAX_ROUNDS_REACHED", "MAX_ROUNDS_REACHED"
            else:
                terminal_state, terminal_status = "NEXT_ROUND_READY", "NEXT_ROUND_REQUIRED"

        evaluations.append(round_evaluation(round_data, round_id, outcome, reasons, {
            "baselineWeightedScore": baseline_score,
            "weightedScore": current_score,
            "baselineOpenBlocking": baseline_open,
            "openBlocking": current_open,
            "closedFindings": int(verification["closedFindings"]),
            "newBlockingFindings": int(verification["newBlockingFindings"]),
        }))
        for reason in reasons:
            add_finding(findings, "REPAIR_ROUND_" + outcome, reason, [str(batch_path.resolve())], round_id)
        previous_round = round_data
        if terminal_state is not None and terminal_state != "NEXT_ROUND_READY":
            break

    if not rounds:
        add_finding(findings, "NO_REPAIR_ROUNDS", "At least one round is required for a bounded repair run.", [str(batch_path.resolve())])
        terminal_state, terminal_status = "BLOCKED", "BLOCKED"
    elif terminal_state is None:
        terminal_state, terminal_status = "MAX_ROUNDS_REACHED", "MAX_ROUNDS_REACHED"
        add_finding(findings, "MAX_ROUNDS_REACHED", "The repair run ended without a passing independent verification.", [str(batch_path.resolve())])

    if terminal_state == "READY_FOR_HUMAN_SUBMISSION" and covered != all_change_set_ids:
        add_finding(findings, "CHANGE_SET_COVERAGE_INCOMPLETE", "Not all Change Sets were covered by repair rounds.", [str(batch_path.resolve())])
        terminal_state, terminal_status = "BLOCKED", "BLOCKED"
    if terminal_state == "READY_FOR_HUMAN_SUBMISSION":
        first = rounds[0]["verification"] if rounds else {}
        if first.get("externalGateStatus") in {"FAIL", "ENVIRONMENT_BLOCKED"}:
            terminal_state, terminal_status = "BLOCKED", "BLOCKED"

    final_open = int(rounds[-1]["verification"]["openBlocking"]) if rounds else 0
    return run_payload(
        batch,
        batch_path,
        policy,
        policy_path,
        evaluations,
        terminal_state or "BLOCKED",
        terminal_status or "BLOCKED",
        findings,
        sorted(repeated_roots),
        initial_open_blocking,
        final_open,
        scope_violations,
        independent_failures,
        covered,
        all_change_set_ids,
    )


def round_evaluation(round_data: dict[str, Any], round_id: str, outcome: str, reasons: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "roundId": round_id,
        "roundIndex": int(round_data.get("roundIndex", 1)),
        "revision": str(round_data.get("revision", "unknown")),
        "changeSetIds": [str(item) for item in round_data.get("changeSetIds", [])],
        "outcome": outcome,
        "reasons": reasons,
        "metrics": metrics,
    }


def run_payload(batch: dict[str, Any], batch_path: Path, policy: dict[str, Any], policy_path: Path, evaluations: list[dict[str, Any]], state: str, status: str, findings: list[dict[str, Any]], repeated_roots: list[str], initial_open: int, final_open: int, scope_violations: int, independent_failures: int, covered: set[str] | None = None, all_change_set_ids: set[str] | None = None) -> dict[str, Any]:
    covered = covered or set()
    all_change_set_ids = all_change_set_ids or {str(item.get("changeSetId")) for item in batch.get("changeSets", []) if item.get("changeSetId")}
    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": str(batch.get("workflowId", "unknown")),
        "targetRevision": str(batch.get("targetRevision", "unknown")),
        "mode": "SHADOW_ONLY",
        "sourceChangeSetBatch": str(batch_path.resolve()),
        "policy": {"path": str(policy_path.resolve()), "policyId": policy.get("policyId")},
        "state": state,
        "status": status,
        "roundEvaluations": evaluations,
        "metrics": {
            "rounds": len(evaluations),
            "coveredChangeSets": len(covered),
            "remainingChangeSets": len(all_change_set_ids - covered),
            "initialOpenBlocking": initial_open,
            "finalOpenBlocking": final_open,
            "repeatedRootCauseIds": repeated_roots,
            "scopeViolations": scope_violations,
            "independentVerificationFailures": independent_failures,
        },
        "findings": findings,
        "closureEligible": False,
        "externalSubmissionAllowed": False,
        "createdAt": now(),
    }
    result = {"runId": "BOUNDED-REPAIR-RUN-" + canonical_hash(payload_without_id)[:16], **payload_without_id}
    errors = validate_schema_value(result, "bounded-repair-run.schema.json")
    if errors:
        raise ValueError("invalid bounded repair run: " + "; ".join(errors))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-set-batch", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--round", action="append", type=Path, required=True, help="Bounded repair round evidence; repeat in order.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        batch = load(args.change_set_batch.resolve())
        policy = load(args.policy.resolve())
        rounds = [load(path.resolve()) for path in args.round]
        result = evaluate(batch, rounds, policy, args.change_set_batch.resolve(), args.policy.resolve())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), result)
    print(json.dumps({
        "status": result["status"],
        "state": result["state"],
        "closureEligible": result["closureEligible"],
        "coveredChangeSets": result["metrics"]["coveredChangeSets"],
        "rounds": result["metrics"]["rounds"],
        "repeatedRootCauseIds": result["metrics"]["repeatedRootCauseIds"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY_FOR_HUMAN_SUBMISSION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
