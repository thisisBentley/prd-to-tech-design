#!/usr/bin/env python3
"""Deterministic semantic consistency review over a frozen evidence ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECK_AXES = [
    ("SEMANTIC.TERMINOLOGY", "terminologyClaims"),
    ("SEMANTIC.CAPABILITY", "capabilityClaims"),
    ("SEMANTIC.STATE", "stateAssumptions"),
    ("SEMANTIC.PERMISSION", "permissionEdges"),
    ("SEMANTIC.AUTHORITY_SYNC", "crossArtifactClaims"),
    ("SEMANTIC.PROVENANCE", "businessAssertions"),
]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def finding(
    finding_id: str,
    title: str,
    evidence_refs: list[str],
    impact: str,
    close_condition: str,
    root_cause_id: str,
    invariant: str,
) -> dict[str, Any]:
    return {
        "findingId": finding_id,
        "severity": "BLOCKING",
        "title": title,
        "evidenceRefs": evidence_refs or ["semantic-review-input"],
        "impact": impact,
        "closeCondition": close_condition,
        "owner": "delivery-producer",
        "rootCauseId": root_cause_id,
        "repairClass": "SEMANTIC",
        "expectedInvariant": invariant,
        "regressionTests": ["python -m unittest tests.test_semantic_consistency_cases"],
    }


def review(data: dict[str, Any], source_path: Path, transcript_path: Path, review_plan_id: str | None, target_handoff_id: str | None, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    by_axis: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for index, item in enumerate(data.get("artifacts", [])):
        path = Path(item.get("path", ""))
        if not path.is_absolute():
            path = source_path.parent / path
        refs = [str(path.resolve())]
        if not path.exists():
            item_finding = finding(
                f"SEM-ARTIFACT-{index + 1:02d}", "Review artifact is missing",
                refs, "Semantic review cannot prove claims against a missing artifact.",
                "Restore the frozen artifact and rerun semantic review.", "SEMANTIC.ARTIFACT.MISSING",
                "Every declared artifact exists and its SHA-256 matches the frozen ledger.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.PROVENANCE"].append(item_finding)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            item_finding = finding(
                f"SEM-ARTIFACT-{index + 1:02d}", "Review artifact hash mismatch",
                refs, "The evidence ledger points to content different from the reviewed artifact.",
                "Re-freeze the artifact or correct the ledger, then rerun review.", "SEMANTIC.ARTIFACT.HASH",
                "Every declared artifact exists and its SHA-256 matches the frozen ledger.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.PROVENANCE"].append(item_finding)

    for index, item in enumerate(data.get("terminologyClaims", [])):
        refs = list(item.get("evidenceRefs", []))
        if item.get("grounding") != "GROUNDED" or not refs:
            item_finding = finding(
                f"SEM-TERM-{index + 1:02d}", "Terminology is ungrounded or conflicting",
                refs, f"Term {item.get('usedName')} cannot be reconciled to {item.get('canonicalName')} from evidence.",
                "Bind the term to a canonical capability, requirement or decision source.", "SEMANTIC.TERMINOLOGY.GROUNDING",
                "Every canonical term, alias and new term has an explicit grounded basis.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.TERMINOLOGY"].append(item_finding)

    for index, item in enumerate(data.get("capabilityClaims", [])):
        refs = list(item.get("sourceRefs", [])) + list(item.get("verificationEvidenceRefs", []))
        declared = item.get("declaredStatus")
        verified = item.get("verificationStatus")
        expected = {"EXISTING": "VERIFIED_EXISTING", "EXTENSION": "VERIFIED_EXTENSION", "NEW": "VERIFIED_NEW"}
        if not refs or verified in {"HOLD", "REJECTED"} or (declared in expected and expected[declared] != verified):
            item_finding = finding(
                f"SEM-CAP-{index + 1:02d}", "Capability identity is unverified or misclassified",
                refs, f"Capability {item.get('capabilityId')} is declared {declared} but verified as {verified}.",
                "Re-research the capability using available Jira, MCP or Git evidence and classify it consistently.", "SEMANTIC.CAPABILITY.IDENTITY",
                "Declared and verified capability statuses agree and are supported by retained evidence.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.CAPABILITY"].append(item_finding)

    for index, item in enumerate(data.get("stateAssumptions", [])):
        refs = list(item.get("evidenceRefs", []))
        if not item.get("preconditionDefined") or not item.get("reachableFrom") or not refs:
            item_finding = finding(
                f"SEM-STATE-{index + 1:02d}", "State assumption lacks an explicit precondition",
                refs, f"State {item.get('stateId')} can be reached or rendered without a proven precondition.",
                "Define the source state, transition and visible precondition, then resync PRD and prototype.", "SEMANTIC.STATE.PRECONDITION",
                "Every visible state has a source, transition path and explicit precondition.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.STATE"].append(item_finding)

    edges: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, item in enumerate(data.get("permissionEdges", [])):
        refs = list(item.get("evidenceRefs", []))
        key = (str(item.get("role")), str(item.get("action")), str(item.get("resource")))
        edges[key].append((index, item))
        if item.get("decision") == "UNSPECIFIED" or not refs:
            item_finding = finding(
                f"SEM-PERM-{index + 1:02d}", "Permission boundary is unspecified",
                refs, f"{key[0]} -> {key[1]} on {key[2]} has no evidence-backed decision.",
                "Specify allow/deny and its condition or provide an authoritative source.", "SEMANTIC.PERMISSION.UNSPECIFIED",
                "Every permission edge is explicitly allowed or denied with evidence.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.PERMISSION"].append(item_finding)
    for key, entries in edges.items():
        decisions = {entry.get("decision") for _, entry in entries}
        if "ALLOWED" in decisions and "DENIED" in decisions:
            refs = [ref for _, entry in entries for ref in entry.get("evidenceRefs", [])]
            item_finding = finding(
                f"SEM-PERM-CONFLICT-{len(by_axis['SEMANTIC.PERMISSION']) + 1:02d}", "Permission decision conflicts",
                refs, f"{key[0]} -> {key[1]} on {key[2]} is both allowed and denied.",
                "Reconcile the authoritative role and condition model.", "SEMANTIC.PERMISSION.CONFLICT",
                "A role/action/resource tuple has one unambiguous permission decision.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.PERMISSION"].append(item_finding)

    for index, item in enumerate(data.get("crossArtifactClaims", [])):
        refs = list(item.get("evidenceRefs", []))
        status = item.get("status")
        if status != "EQUAL" or not refs:
            title = "PRD and Prototype require resynchronization" if status == "CONFLICT" else "Cross-artifact semantic state is unverified"
            root = "SEMANTIC.AUTHORITY.RESYNC_REQUIRED" if status == "CONFLICT" else "SEMANTIC.AUTHORITY.UNVERIFIED"
            item_finding = finding(
                f"SEM-AUTH-{index + 1:02d}", title, refs,
                f"Topic {item.get('topic')} differs or cannot be compared across authority domains: business={item.get('businessValue')} interaction={item.get('interactionValue')}.",
                "Open reconciliation, repair the non-authoritative domain or the source domain with product evidence, then re-seal the pair.",
                root, "Business facts remain PRD-authoritative, interaction facts remain Prototype-authoritative, and pairStatus is SYNCED.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.AUTHORITY_SYNC"].append(item_finding)

    for index, item in enumerate(data.get("businessAssertions", [])):
        refs = list(item.get("evidenceRefs", []))
        if not refs or item.get("sourceType") == "INFERENCE":
            item_finding = finding(
                f"SEM-SOURCE-{index + 1:02d}", "Business assertion is not traceable to evidence",
                refs, f"Unsupported business claim: {item.get('statement')}.",
                "Replace inference with verified fact or route the unresolved choice through Research/Decision.", "SEMANTIC.PROVENANCE.UNSOURCED",
                "Every business assertion is sourced to the requirement, a closed decision or retained evidence.",
            )
            findings.append(item_finding); by_axis["SEMANTIC.PROVENANCE"].append(item_finding)

    if coverage is not None and coverage.get("status") != "PASS":
        missing = coverage.get("missing", [])
        coverage_finding = finding(
            "SEM-COVERAGE-001", "Semantic evidence coverage is incomplete", coverage.get("evidenceRefs", [str(source_path.resolve())]),
            "The reviewer omitted reachable FR/AC/BR identifiers, visible interactions, states or known capability claims from the evidence ledger: " + ", ".join(missing[:20]),
            "Populate the frozen semantic ledger for every required item and rerun the independent review.",
            "SEMANTIC.COVERAGE.INCOMPLETE", "Every PRD identifier, visible interaction and known capability is represented in semantic evidence.",
        )
        findings.append(coverage_finding); by_axis["SEMANTIC.PROVENANCE"].append(coverage_finding)

    checks = []
    for axis, key in CHECK_AXES:
        applicable = data.get(key, [])
        axis_findings = by_axis.get(axis, [])
        if not applicable:
            status = "not_executed"
            missing = finding(
                f"SEM-MISSING-{axis.split('.')[-1]}",
                f"Required semantic axis {axis} was not executed",
                [str(source_path.resolve())],
                "A complete semantic review cannot be claimed when one of the six required axes has no evidence.",
                "Populate the frozen semantic evidence ledger for this axis and rerun the independent review.",
                "SEMANTIC.EVIDENCE.INCOMPLETE",
                "All six semantic axes are executed with evidence before Quality Exit.",
            )
            findings.append(missing)
            by_axis[axis].append(missing)
            axis_findings = by_axis[axis]
        else:
            status = "failed" if axis_findings else "passed"
        refs = []
        for item in applicable:
            refs.extend(item.get("evidenceRefs", []))
            refs.extend(item.get("sourceRefs", []))
            refs.extend(item.get("verificationEvidenceRefs", []))
        checks.append({
            "checkId": axis,
            "status": status,
            "evidenceRefs": list(dict.fromkeys(refs)) or [str(source_path.resolve())],
            "observed": f"claims={len(applicable)} blockingFindings={len(axis_findings)}",
            "expected": "every claim is evidence-backed and consistent across authority domains",
        })

    if coverage is not None:
        checks.append({
            "checkId": "SEMANTIC.COVERAGE",
            "status": "passed" if coverage.get("status") == "PASS" else "failed",
            "evidenceRefs": coverage.get("evidenceRefs", [str(source_path.resolve())]),
            "observed": f"missing={len(coverage.get('missing', []))}",
            "expected": "every reachable semantic item is represented in the ledger",
        })
    incomplete = any(check["status"] == "not_executed" for check in checks)
    verdict = "INCOMPLETE" if incomplete else ("RETURNED" if findings else "ACCEPTED")
    workflow_id = data["workflowId"]
    target_revision = data["targetRevision"]
    context_id = "semantic-review-" + hashlib.sha256((workflow_id + target_revision).encode()).hexdigest()[:12]
    review_run_id = "REV-SEM-" + hashlib.sha256(source_path.read_bytes() + transcript_path.name.encode()).hexdigest()[:16]
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        f"semantic-review workflow={workflow_id} revision={target_revision} "
        f"claims={sum(len(data.get(key, [])) for _, key in CHECK_AXES)} findings={len(findings)} verdict={verdict}\n",
        encoding="utf-8",
    )
    return {
        "schemaVersion": 1,
        "reviewRunId": review_run_id,
        "reviewPlanId": review_plan_id or f"RP-{workflow_id}-SEMANTIC",
        "workflowId": workflow_id,
        "producerRole": data.get("producerRole", "prd-producer"),
        "reviewerRole": "semantic-consistency-reviewer",
        "reviewType": "independent",
        "targetHandoffId": target_handoff_id or f"HO-{workflow_id}-{target_revision}",
        "targetRevision": target_revision,
        "independentContext": True,
        "verdict": verdict,
        "completionStatus": "partial" if incomplete else "complete",
        "checks": checks,
        "findings": findings,
        "blockingCount": len(findings),
        "evidenceRefs": [str(source_path.resolve()), str(transcript_path.resolve())],
        "reviewerContextId": context_id,
        "reviewerTranscript": str(transcript_path.resolve()),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--review-plan-id")
    parser.add_argument("--target-handoff-id")
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--allow-returned", action="store_true", help="Return zero while still emitting RETURNED/INCOMPLETE for orchestrated recheck.")
    args = parser.parse_args()
    data = load(args.input)
    transcript = args.transcript or args.out.with_suffix(".log")
    coverage = load(args.coverage) if args.coverage else None
    result = review(data, args.input.resolve(), transcript, args.review_plan_id, args.target_handoff_id, coverage)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["verdict"], "blockingCount": result["blockingCount"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["verdict"] == "ACCEPTED" or args.allow_returned else 1


if __name__ == "__main__":
    raise SystemExit(main())
