#!/usr/bin/env python3
"""Evaluate product-manager and architect consumer readiness for one real-case candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import now, validate_schema_value
from validate_delivery_artifacts import validate as validate_delivery_artifacts

TAG_RE = re.compile(r"<[^>]+>")
HEADING_RE = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")


def visible(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html)).strip()


def section_text(html: str, title: str) -> str:
    match = re.search(rf"<h[1-6][^>]*>[^<]*{re.escape(title)}[^<]*</h[1-6]>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    next_heading = HEADING_RE.search(html, match.end())
    end = next_heading.start() if next_heading else len(html)
    return visible(html[match.end():end])


def add_finding(findings: list[dict[str, Any]], domain: str, code: str, severity: str, message: str, refs: list[str]) -> None:
    payload = {"domain": domain, "code": code, "severity": severity, "message": message, "evidenceRefs": refs}
    findings.append({"findingId": "CONSUMER-" + code + "-" + canonical_hash(payload)[:12], **payload})


def add_check(checks: list[dict[str, Any]], domain: str, check_id: str, passed: bool, observed: Any, expected: Any, refs: list[str]) -> None:
    checks.append({
        "domain": domain,
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
        "evidenceRefs": refs,
    })


def ac_blocks(prd_text: str) -> dict[str, str]:
    lines = prd_text.splitlines()
    positions = [(index, ac) for index, line in enumerate(lines) for ac in AC_RE.findall(line)]
    result: dict[str, str] = {}
    for index, ac in positions:
        end = len(lines)
        for next_index in range(index + 1, len(lines)):
            if AC_RE.search(lines[next_index]) or FR_RE.search(lines[next_index]) and lines[next_index].lstrip().startswith("#"):
                end = next_index
                break
        result.setdefault(ac, "\n".join(lines[index:min(end, index + 12)]).strip())
    return result


def validate_source_lock(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        data = load(path)
    except Exception as exc:
        return [], [f"invalid source lock: {exc}"]
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, list):
        return [], ["source lock has no sources array"]
    verified: list[dict[str, Any]] = []
    for item in sources:
        if not isinstance(item, dict):
            errors.append("source lock entry is not an object")
            continue
        source_path = Path(str(item.get("path") or "")).expanduser()
        declared = str(item.get("sha256") or "")
        if not source_path.is_file():
            errors.append(f"source is not locally resolvable: {source_path}")
            continue
        actual = sha256_file(source_path)
        if declared != actual:
            errors.append(f"source hash drift: {source_path}")
            continue
        verified.append({
            "role": str(item.get("role") or item.get("sourceType") or "UNKNOWN"),
            "sourceType": str(item.get("sourceType") or item.get("role") or "UNKNOWN"),
            "path": str(source_path.resolve()),
            "sha256": actual,
        })
    return verified, errors


def validate_consumer_review(
    review_path: Path,
    actor: dict[str, str],
    producer: dict[str, str],
    workflow_id: str,
    revision: str,
) -> tuple[bool, dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        review = load(review_path)
    except Exception as exc:
        return False, {}, [f"invalid consumer review: {exc}"]
    errors.extend(validate_schema_value(review, "review-result.schema.json"))
    if review.get("workflowId") != workflow_id:
        errors.append("consumer review workflowId mismatch")
    if review.get("targetRevision") != revision:
        errors.append("consumer review targetRevision mismatch")
    if review.get("producerRole") != producer.get("role"):
        errors.append("consumer review producerRole mismatch")
    if review.get("reviewerRole") != actor.get("role"):
        errors.append("consumer review reviewerRole mismatch")
    if review.get("reviewerContextId") != actor.get("contextId"):
        errors.append("consumer review contextId mismatch")
    if review.get("independentContext") is not True:
        errors.append("consumer review is not independent")
    if review.get("verdict") != "ACCEPTED":
        errors.append(f"consumer review verdict {review.get('verdict')} is not ACCEPTED")
    if review.get("completionStatus") != "complete":
        errors.append("consumer review completionStatus is not complete")
    if int(review.get("blockingCount", 0)) != 0:
        errors.append("consumer review has blocking findings")
    if not review.get("checks") or any(item.get("status") != "passed" for item in review.get("checks", [])):
        errors.append("consumer review has non-passing or empty checks")
    transcript_value = str(review.get("reviewerTranscript") or "").strip()
    if not transcript_value:
        errors.append("consumer review has no transcript")
    else:
        transcript = Path(transcript_value)
        if not transcript.is_absolute():
            transcript = review_path.parent / transcript
        if not transcript.is_file() or transcript.stat().st_size == 0:
            errors.append(f"consumer review transcript is missing or empty: {transcript}")
    runtime_value = str(review.get("reviewerRuntimeRecordPath") or "").strip()
    if not runtime_value:
        errors.append("consumer review has no reviewerRuntimeRecordPath")
    else:
        runtime_path = Path(runtime_value)
        if not runtime_path.is_absolute():
            runtime_path = review_path.parent / runtime_path
        if not runtime_path.is_file():
            errors.append(f"consumer runtime record is missing: {runtime_path}")
        else:
            runtime = load(runtime_path)
            errors.extend("runtime: " + item for item in validate_schema_value(runtime, "agent-runtime-record.schema.json"))
            if runtime.get("workflowId") != workflow_id:
                errors.append("consumer runtime workflowId mismatch")
            if runtime.get("contextId") != actor.get("contextId"):
                errors.append("consumer runtime contextId mismatch")
            if runtime.get("status") != "SUCCEEDED":
                errors.append(f"consumer runtime status {runtime.get('status')} is not SUCCEEDED")
            structured = Path(str(runtime.get("structuredResultPath") or ""))
            if not structured.is_absolute():
                structured = runtime_path.parent / structured
            if not structured.is_file():
                errors.append(f"consumer structured result is missing: {structured}")
            elif structured.resolve() != review_path.resolve():
                errors.append("consumer runtime structuredResultPath does not point to the review result")
            elif runtime.get("structuredResultSha256") != sha256_file(review_path):
                errors.append("consumer runtime structuredResultSha256 does not match the review result")
            task_manifest = Path(str(runtime.get("taskManifest") or ""))
            if not task_manifest.is_absolute():
                task_manifest = runtime_path.parent / task_manifest
            if not task_manifest.is_file():
                errors.append(f"consumer task manifest is missing: {task_manifest}")
            elif runtime.get("taskManifestSha256") != sha256_file(task_manifest):
                errors.append("consumer taskManifestSha256 does not match the task manifest")
            else:
                task = load(task_manifest)
                if task.get("workflowId") != workflow_id:
                    errors.append("consumer task workflowId mismatch")
                if task.get("role") != actor.get("role"):
                    errors.append("consumer task role mismatch")
                if task.get("contextId") != actor.get("contextId"):
                    errors.append("consumer task contextId mismatch")
    return not errors, review, errors


def evaluate(request: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    request_errors = validate_schema_value(request, "consumer-acceptance-request.schema.json")
    policy_errors = validate_schema_value(policy, "consumer-acceptance-policy.schema.json")
    if request_errors or policy_errors:
        raise ValueError("; ".join([*request_errors, *policy_errors]))

    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    artifacts = request["artifacts"]
    paths = {name: Path(value).expanduser().resolve() for name, value in artifacts.items() if value}
    producer = request["producer"]
    pm = request["productManager"]
    architect = request["architect"]
    contexts = [producer["contextId"], pm["contextId"], architect["contextId"]]
    roles = [producer["role"], pm["role"], architect["role"]]
    independent = len(contexts) == len(set(contexts)) and len(roles) == len(set(roles))
    add_check(checks, "SHARED", "CONSUMER.INDEPENDENT_CONTEXTS", independent, {"roles": roles, "contexts": contexts}, "producer, product-manager and architect roles and contexts are distinct", list(artifacts.values()))
    if not independent:
        add_finding(findings, "SHARED", "CONSUMER_CONTEXT_NOT_INDEPENDENT", "BLOCKING", "Consumer proxy contexts must differ from producer and from each other.", list(artifacts.values()))

    review_paths = {
        "PRODUCT_MANAGER": (paths.get("productManagerReview"), request["productManager"]),
        "ARCHITECT": (paths.get("architectReview"), request["architect"]),
    }
    for domain, (review_path, actor) in review_paths.items():
        if review_path and review_path.is_file():
            review_ok, review, review_errors = validate_consumer_review(review_path, actor, producer, request["workflowId"], request["targetRevision"])
            add_check(checks, domain, f"{domain}.REVIEW.AUTHORITY", review_ok, {"verdict": review.get("verdict"), "reviewRunId": review.get("reviewRunId"), "errors": review_errors}, "ACCEPTED independent review bound to runtime, task, result hash and transcript", [str(review_path)])
            if not review_ok:
                add_finding(findings, domain, f"{domain}_REVIEW_NOT_AUTHORITATIVE", "BLOCKING", "Consumer review is not independently authoritative: " + "; ".join(review_errors), [str(review_path)])

    required_paths = ["prd", "overview", "jira", "prdReviewResult", "decisionContract", "decisionReadiness", "sourceLock", "productManagerReview", "architectReview"]
    missing = [name for name in required_paths if not paths.get(name) or not paths[name].is_file()]
    if request["artifactProfile"] in {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}:
        missing.extend(name for name in ("prototype", "prototypeManifest", "runtimeEvidence") if not paths.get(name) or not paths[name].is_file())
    add_check(checks, "SHARED", "CONSUMER.REQUIRED_INPUTS", not missing, missing, [], list(artifacts.values()))
    if missing:
        add_finding(findings, "SHARED", "CONSUMER_REQUIRED_INPUT_MISSING", "BLOCKING", "Required consumer acceptance inputs are missing: " + ", ".join(missing) + ".", list(artifacts.values()))
        return build_report(request, checks, findings, {}, paths)

    prd_text = paths["prd"].read_text(encoding="utf-8", errors="replace")
    overview_text = paths["overview"].read_text(encoding="utf-8", errors="replace")
    thresholds = policy["thresholds"]
    placeholder_hits = [pattern for pattern in policy["blockingPlaceholderPatterns"] if re.search(re.escape(pattern), prd_text + "\n" + overview_text, re.IGNORECASE)]
    add_check(checks, "SHARED", "CONSUMER.NO_BLOCKING_PLACEHOLDERS", not placeholder_hits, placeholder_hits, [], [str(paths["prd"]), str(paths["overview"])])
    if placeholder_hits:
        add_finding(findings, "SHARED", "CONSUMER_PLACEHOLDER_PRESENT", "QUALITY", "Unresolved placeholder text remains: " + ", ".join(placeholder_hits) + ".", [str(paths["prd"]), str(paths["overview"])])

    art = validate_delivery_artifacts(
        paths["prd"],
        request["artifactProfile"],
        "provided",
        paths.get("prototype"),
        paths.get("prototypeManifest"),
        paths["overview"],
        paths.get("jira"),
        "provided",
        paths.get("runtimeEvidence"),
    )
    add_check(checks, "SHARED", "CONSUMER.ARTIFACT_CONTRACT", art.get("status") == "PASS", art.get("status"), "PASS", [str(path) for path in paths.values()])
    if art.get("status") != "PASS":
        add_finding(findings, "SHARED", "CONSUMER_ARTIFACT_CONTRACT_FAILED", "BLOCKING", "Existing delivery artifact contract did not pass.", [str(path) for path in paths.values()])

    # Product-manager consumer proxy.
    add_check(checks, "PRODUCT_MANAGER", "PM.PRD.CONTENT_LENGTH", len(prd_text) >= thresholds["minPrdChars"], len(prd_text), thresholds["minPrdChars"], [str(paths["prd"])])
    if len(prd_text) < thresholds["minPrdChars"]:
        add_finding(findings, "PRODUCT_MANAGER", "PM_PRD_TOO_THIN", "QUALITY", "PRD is too thin for a product review.", [str(paths["prd"])])
    prd_lower = prd_text.lower()
    missing_topics = [topic for topic, aliases in policy["requiredPrdTopics"].items() if not any(alias.lower() in prd_lower for alias in aliases)]
    add_check(checks, "PRODUCT_MANAGER", "PM.PRD.REQUIRED_TOPICS", not missing_topics, missing_topics, [], [str(paths["prd"])])
    if missing_topics:
        add_finding(findings, "PRODUCT_MANAGER", "PM_PRD_TOPICS_MISSING", "QUALITY", "PRD lacks reviewable topics: " + ", ".join(missing_topics) + ".", [str(paths["prd"])])

    frs = sorted(set(FR_RE.findall(prd_text)))
    acs = sorted(set(AC_RE.findall(prd_text)))
    weak_acs = [ac for ac, block in ac_blocks(prd_text).items() if len(block) < thresholds["minAcBlockChars"] or sum(token in block.lower() for token in ("when", "then", "given", "前置", "触发", "结果", "验证")) < 2]
    add_check(checks, "PRODUCT_MANAGER", "PM.PRD.AC_EXECUTABLE", bool(acs) and not weak_acs, {"frCount": len(frs), "acCount": len(acs), "weakAcs": weak_acs}, {"frCount": ">=1", "acCount": ">=1", "weakAcs": []}, [str(paths["prd"])])
    if not acs or weak_acs:
        add_finding(findings, "PRODUCT_MANAGER", "PM_AC_NOT_EXECUTABLE", "QUALITY", "Acceptance criteria are missing or too weak to execute: " + ", ".join(weak_acs), [str(paths["prd"])])

    missing_tabs = [tab for tab in policy["requiredOverviewTabs"] if len(section_text(overview_text, tab)) < thresholds["minOverviewTabChars"]]
    add_check(checks, "PRODUCT_MANAGER", "PM.OVERVIEW.TAB_CONTENT", not missing_tabs, missing_tabs, [], [str(paths["overview"])])
    if missing_tabs:
        add_finding(findings, "PRODUCT_MANAGER", "PM_OVERVIEW_THIN", "QUALITY", "Overview tabs are missing or too thin: " + ", ".join(missing_tabs) + ".", [str(paths["overview"])])
    source_hash = hashlib.sha256(paths["prd"].read_bytes()).hexdigest()
    add_check(checks, "PRODUCT_MANAGER", "PM.OVERVIEW.SOURCE_HASH", source_hash in overview_text, source_hash, source_hash, [str(paths["overview"]), str(paths["prd"])])
    if source_hash not in overview_text:
        add_finding(findings, "PRODUCT_MANAGER", "PM_OVERVIEW_SOURCE_DRIFT", "BLOCKING", "Overview does not bind to the current PRD hash.", [str(paths["overview"]), str(paths["prd"])])

    if request["artifactProfile"] in {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}:
        prototype_text = paths["prototype"].read_text(encoding="utf-8", errors="replace")
        manifest = load(paths["prototypeManifest"])
        bindings = re.findall(r'data-ai-id="[^"]+"', prototype_text, re.IGNORECASE)
        state_values: set[str] = set()
        for value in re.findall(r'data-ai-state="([^"]+)"', prototype_text, re.IGNORECASE):
            state_values.update(part.strip() for part in re.split(r"[,|]", value) if part.strip())
        for element in manifest.get("elements", []) or []:
            state_values.update(str(item) for item in element.get("states", []) or [])
        state_text = " ".join(sorted(state_values)).lower()
        required_state_kind = any(kind.lower() in state_text for kind in policy["requiredPrototypeStateKinds"])
        permission_markers = bool(re.search(r"data-ai-permission|permission", prototype_text, re.IGNORECASE)) or any((item.get("permissions") or []) for item in manifest.get("elements", []) or [])
        prototype_ok = len(bindings) >= thresholds["minPrototypeBindings"] and len(state_values) >= thresholds["minPrototypeStates"] and required_state_kind and permission_markers
        add_check(checks, "PRODUCT_MANAGER", "PM.PROTOTYPE.BEHAVIORAL_COVERAGE", prototype_ok, {"bindings": len(bindings), "states": sorted(state_values), "permissionMarkers": permission_markers}, {"minBindings": thresholds["minPrototypeBindings"], "minStates": thresholds["minPrototypeStates"], "requiredStateKind": True, "permissionMarkers": True}, [str(paths["prototype"]), str(paths["prototypeManifest"])])
        if not prototype_ok:
            add_finding(findings, "PRODUCT_MANAGER", "PM_PROTOTYPE_BEHAVIOR_GAP", "QUALITY", "Prototype does not demonstrate enough bindings, states, exception coverage or permission behavior.", [str(paths["prototype"]), str(paths["prototypeManifest"])])
        runtime = load(paths["runtimeEvidence"])
        prototype_hash = hashlib.sha256(paths["prototype"].read_bytes()).hexdigest()
        runtime_ok = runtime.get("status") == "PASS" and runtime.get("runtimeEvidenceLevel") == "REAL_BROWSER" and runtime.get("prototypeHash") == prototype_hash and not runtime.get("consoleErrors") and not runtime.get("pageErrors") and not runtime.get("requestFailures")
        add_check(checks, "PRODUCT_MANAGER", "PM.PROTOTYPE.RUNTIME_AUTHORITY", runtime_ok, {"status": runtime.get("status"), "level": runtime.get("runtimeEvidenceLevel"), "hash": runtime.get("prototypeHash"), "currentHash": prototype_hash}, "PASS / REAL_BROWSER / current hash / zero errors", [str(paths["runtimeEvidence"]), str(paths["prototype"])])
        if not runtime_ok:
            add_finding(findings, "PRODUCT_MANAGER", "PM_PROTOTYPE_RUNTIME_NOT_AUTHORITATIVE", "BLOCKING", "Prototype runtime evidence is not authoritative for the current Prototype hash.", [str(paths["runtimeEvidence"]), str(paths["prototype"])])

    # Architect consumer proxy.
    review = load(paths["prdReviewResult"])
    review_pass = str(review.get("result") or review.get("status") or "").upper() == "PASS"
    add_check(checks, "ARCHITECT", "ARCH.PRD.REVIEW_PASS", review_pass, review.get("result") or review.get("status"), "PASS", [str(paths["prdReviewResult"])])
    if not review_pass:
        add_finding(findings, "ARCHITECT", "ARCH_PRD_REVIEW_NOT_PASS", "BLOCKING", "PRD review result is not PASS.", [str(paths["prdReviewResult"])])
    contract = load(paths["decisionContract"])
    readiness = load(paths["decisionReadiness"])
    contract_ok = contract.get("status") == "PASS" and contract.get("readiness") == "READY" and int((contract.get("metrics") or {}).get("openBlocking", -1)) == 0 and contract.get("prdSha256") == source_hash and not contract.get("traceability", {}).get("uncoveredP0P1ObjectIds")
    add_check(checks, "ARCHITECT", "ARCH.DECISION_CONTRACT.READY", contract_ok, {"status": contract.get("status"), "readiness": contract.get("readiness"), "openBlocking": (contract.get("metrics") or {}).get("openBlocking"), "prdHashMatches": contract.get("prdSha256") == source_hash}, {"status": "PASS", "readiness": "READY", "openBlocking": 0, "prdHashMatches": True}, [str(paths["decisionContract"]), str(paths["prd"])])
    if not contract_ok:
        add_finding(findings, "ARCHITECT", "ARCH_DECISION_CONTRACT_NOT_READY", "BLOCKING", "Decision Contract is not READY for this PRD revision.", [str(paths["decisionContract"]), str(paths["prd"])])
    readiness_ok = readiness.get("status") == "PASS" and not readiness.get("errors")
    add_check(checks, "ARCHITECT", "ARCH.DECISION_READINESS.PASS", readiness_ok, readiness, {"status": "PASS", "errors": []}, [str(paths["decisionReadiness"])])
    if not readiness_ok:
        add_finding(findings, "ARCHITECT", "ARCH_DECISION_READINESS_NOT_PASS", "BLOCKING", "Decision readiness report is not PASS.", [str(paths["decisionReadiness"])])
    verified_sources, source_errors = validate_source_lock(paths["sourceLock"])
    technical_sources = [item for item in verified_sources if item["sourceType"].upper() not in {"PRD", "REQUIREMENT", "DECISION_CONTEXT"} and item["role"].lower() not in {"prd", "requirement"}]
    source_ok = not source_errors and len(verified_sources) >= thresholds["minSourceCount"] and bool(technical_sources)
    add_check(checks, "ARCHITECT", "ARCH.SOURCE_LOCK.CONSUMABLE", source_ok, {"sources": verified_sources, "errors": source_errors}, {"minSources": thresholds["minSourceCount"], "technicalSource": True, "errors": []}, [str(paths["sourceLock"])])
    if not source_ok:
        add_finding(findings, "ARCHITECT", "ARCH_SOURCE_LOCK_NOT_CONSUMABLE", "BLOCKING", "Source lock is incomplete, drifted or lacks a technical source: " + "; ".join(source_errors), [str(paths["sourceLock"])])

    artifact_hashes = {name: sha256_file(path) if path.is_file() else None for name, path in paths.items()}
    return build_report(request, checks, findings, artifact_hashes, paths)


def build_report(request: dict[str, Any], checks: list[dict[str, Any]], findings: list[dict[str, Any]], artifact_hashes: dict[str, str | None], paths: dict[str, Path]) -> dict[str, Any]:
    if any(item["severity"] == "BLOCKING" for item in findings):
        status = "BLOCKED"
    elif findings:
        status = "NEEDS_REVIEW"
    else:
        status = "PASS"
    pm_checks = [item for item in checks if item["domain"] == "PRODUCT_MANAGER"]
    arch_checks = [item for item in checks if item["domain"] == "ARCHITECT"]
    payload = {
        "schemaVersion": 1,
        "workflowId": request["workflowId"],
        "caseId": request["caseId"],
        "targetRevision": request["targetRevision"],
        "caseClassification": request["caseClassification"],
        "evaluationMode": "AGENT_CONSUMER_PROXY",
        "status": status,
        "m7ExitEvidenceEligible": status == "PASS" and request["caseClassification"] == "REAL",
        "humanConsumerReviewRequired": True,
        "productManager": {"role": request["productManager"]["role"], "contextId": request["productManager"]["contextId"], "status": "PASS" if pm_checks and all(item["status"] == "passed" for item in pm_checks) else "BLOCKED"},
        "architect": {"role": request["architect"]["role"], "contextId": request["architect"]["contextId"], "status": "PASS" if arch_checks and all(item["status"] == "passed" for item in arch_checks) else "BLOCKED"},
        "checks": checks,
        "findings": findings,
        "metrics": {
            "checks": len(checks),
            "passed": sum(1 for item in checks if item["status"] == "passed"),
            "failed": sum(1 for item in checks if item["status"] == "failed"),
            "blockingFindings": sum(1 for item in findings if item["severity"] == "BLOCKING"),
            "qualityFindings": sum(1 for item in findings if item["severity"] == "QUALITY"),
        },
        "artifactHashes": artifact_hashes,
    }
    content_hash = canonical_hash(payload)
    return {
        "reportId": "CONSUMER-ACCEPTANCE-" + content_hash[:16],
        **payload,
        "contentSha256": content_hash,
        "createdAt": now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = evaluate(load(args.request.resolve()), load(args.policy.resolve()))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), report)
    print(json.dumps({
        "status": report["status"],
        "m7ExitEvidenceEligible": report["m7ExitEvidenceEligible"],
        "caseId": report["caseId"],
        "productManager": report["productManager"]["status"],
        "architect": report["architect"]["status"],
        "findings": len(report["findings"]),
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
