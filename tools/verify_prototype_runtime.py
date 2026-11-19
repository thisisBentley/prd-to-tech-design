#!/usr/bin/env python3
"""Verify a Prototype through scenario-based real browser replay or a static fallback."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def static_checks(prototype: Path) -> list[dict[str, Any]]:
    text = prototype.read_text(encoding="utf-8", errors="replace")
    external = re.search(r"<(script|link)[^>]+(?:https?:|//)", text, re.I)
    return [
        {"checkId": "HTML.EXISTS", "status": "passed", "observed": "prototype file readable", "expected": "standalone HTML is readable", "evidenceRefs": [str(prototype.resolve())]},
        {"checkId": "HTML.DOCUMENT", "status": "passed" if re.search(r"<html[\s>]|<!doctype html", text, re.I) else "failed", "observed": "HTML document marker present" if re.search(r"<html[\s>]|<!doctype html", text, re.I) else "HTML marker missing", "expected": "standalone HTML document", "evidenceRefs": [str(prototype.resolve())]},
        {"checkId": "HTML.NO_EXTERNAL_RUNTIME", "status": "failed" if external else "passed", "observed": "external dependency found" if external else "no external runtime dependency", "expected": "offline standalone runtime", "evidenceRefs": [str(prototype.resolve())]},
    ]


def run_browser_adapter(runner: list[str], request: dict[str, Any], timeout: float) -> dict[str, Any]:
    process = subprocess.run(
        runner,
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if not process.stdout.strip():
        raise RuntimeError(f"browser runner returned no JSON; stderr={process.stderr[-2000:]}")
    payload = json.loads(process.stdout)
    if not isinstance(payload, dict):
        raise ValueError("browser runner must return a JSON object")
    payload["returnCode"] = process.returncode
    payload["stdout"] = process.stdout
    payload["stderr"] = process.stderr
    return payload


def scenario_checks(results: list[dict[str, Any]], required_state_kinds: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    total = len(results)
    passed = sum(1 for item in results if item.get("status") == "PASS")
    failed = sum(1 for item in results if item.get("status") != "PASS")
    checks.append({"checkId": "RUNTIME.SCENARIOS", "status": "passed" if total > 0 else "failed", "observed": total, "expected": ">=1", "evidenceRefs": []})
    checks.append({"checkId": "RUNTIME.SCENARIO_PASS_RATE", "status": "passed" if total > 0 and failed == 0 else "failed", "observed": {"passed": passed, "failed": failed}, "expected": "all scenarios pass", "evidenceRefs": []})
    covered: set[str] = set()
    for result in results:
        for check in result.get("checks", []):
            if check.get("status") != "passed":
                continue
            check_id = str(check.get("checkId", ""))
            if ".EXPECTED.STATE." in check_id:
                covered.add(check_id.split(".EXPECTED.STATE.", 1)[0])
    # State coverage is also derived from scenario expected states so that a
    # declared but unasserted state cannot silently count as covered.
    for result in results:
        for kind in result.get("coveredStateKinds", []) or []:
            covered.add(str(kind))
    missing = [kind for kind in required_state_kinds if kind not in covered]
    if required_state_kinds:
        checks.append({"checkId": "RUNTIME.STATE_COVERAGE", "status": "passed" if not missing else "failed", "observed": {"covered": sorted(covered), "missing": missing}, "expected": required_state_kinds, "evidenceRefs": []})
    metrics = {"total": total, "passed": passed, "failed": failed, "skipped": sum(1 for item in results if item.get("status") == "SKIPPED"), "coveredStateKinds": sorted(covered)}
    return checks, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser-runner", nargs="+", help="Command that reads a JSON request from stdin and returns browser evidence JSON.")
    parser.add_argument("--browser-timeout", type=float, default=60)
    parser.add_argument("--require-real-browser", action="store_true")
    parser.add_argument("--interaction-contract", type=Path)
    parser.add_argument("--interaction-manifest", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--browser-executable")
    parser.add_argument("--required-state-kind", action="append", default=[])
    args = parser.parse_args()
    prototype = args.prototype.resolve()
    prototype_hash = sha256(prototype)
    checks = list(static_checks(prototype))
    evidence_level = "STATIC_CONTRACT"
    execution_mode = "static-contract"
    browser_version = None
    browser_launch_status = None
    environment_error = None
    screenshots: list[str] = []
    traces: list[str] = []
    dom_snapshots: list[str] = []
    console_errors: list[dict[str, Any] | str] = []
    page_errors: list[Any] = []
    request_failures: list[Any] = []
    scenario_results: list[dict[str, Any]] = []
    scenario_metrics = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "coveredStateKinds": []}
    contract: dict[str, Any] | None = load(args.interaction_contract.resolve()) if args.interaction_contract else None
    interaction_manifest = load(args.interaction_manifest.resolve()) if args.interaction_manifest else None
    contract_checks: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    contract_id = None
    workflow_id = "unknown"
    prototype_revision = "unknown"
    if contract:
        contract_id = str(contract.get("contractId", ""))
        workflow_id = str(contract.get("workflowId", "unknown"))
        prototype_revision = str(contract.get("prototypeRevision", "unknown"))
        contract_hash_ok = contract.get("source", {}).get("prototypeHash") == prototype_hash
        contract_checks.append({"checkId": "RUNTIME.CONTRACT_PROTOTYPE_HASH", "status": "passed" if contract_hash_ok else "failed", "observed": contract.get("source", {}).get("prototypeHash"), "expected": prototype_hash, "evidenceRefs": [str(args.interaction_contract)]})
        scenarios = list(contract.get("runtimeScenarios", []) or [])
        contract_checks.append({"checkId": "RUNTIME.CONTRACT_SCENARIOS", "status": "passed" if scenarios else "failed", "observed": len(scenarios), "expected": ">=1 declared runtime scenario", "evidenceRefs": [str(args.interaction_contract)]})
    evidence_dir = (args.evidence_dir or (args.out.parent / "runtime-evidence")).resolve()
    if args.browser_runner:
        request = {
            "schemaVersion": 1,
            "prototypePath": str(prototype),
            "prototypeHash": prototype_hash,
            "contractPath": str(args.interaction_contract.resolve()) if args.interaction_contract else None,
            "scenarios": scenarios,
            "interactionManifest": interaction_manifest,
            "viewport": {"width": 1440, "height": 900},
            "evidenceDir": str(evidence_dir),
            **({"browserExecutablePath": args.browser_executable} if args.browser_executable else {}),
        }
        try:
            browser = run_browser_adapter(args.browser_runner, request, args.browser_timeout)
            browser_launch_status = str(browser.get("status", "ERROR"))
            execution_mode = str(browser.get("executionMode", "real-browser"))
            evidence_level = "REAL_BROWSER" if execution_mode == "real-browser" else "BROWSER_ADAPTER"
            if browser_launch_status == "ENVIRONMENT_BLOCKED":
                evidence_level = "BROWSER_ADAPTER"
            browser_version = browser.get("browserVersion")
            environment_error = browser.get("error")
            screenshots = [str(item) for item in browser.get("screenshots", []) or []]
            traces = [str(item) for item in browser.get("traces", []) or []]
            dom_snapshots = [str(item) for item in browser.get("domSnapshots", []) or []]
            console_errors = browser.get("consoleErrors", []) or []
            page_errors = browser.get("pageErrors", []) or []
            request_failures = browser.get("requestFailures", []) or []
            scenario_results = browser.get("scenarioResults", []) or []
            for result in scenario_results:
                screenshots.extend(str(item) for item in result.get("evidenceRefs", []) if str(item).endswith(".png"))
                traces.extend(str(item) for item in result.get("evidenceRefs", []) if str(item).endswith(".trace.zip"))
                dom_snapshots.extend(str(item) for item in result.get("evidenceRefs", []) if str(item).endswith(".dom.html"))
            browser_checks = browser.get("checks", [])
            if isinstance(browser_checks, list):
                checks.extend(browser_checks)
            if browser_launch_status == "ENVIRONMENT_BLOCKED":
                checks.append({"checkId": "BROWSER.ENVIRONMENT", "status": "failed", "observed": environment_error or "environment blocked", "expected": "Chromium launches", "evidenceRefs": [str(prototype)]})
            elif browser.get("returnCode") != 0:
                checks.append({"checkId": "BROWSER.RUNNER", "status": "failed", "observed": f"returnCode={browser.get('returnCode')}", "expected": "zero", "evidenceRefs": [str(prototype)]})
            if browser_launch_status not in {"PASS", "FAIL", "ENVIRONMENT_BLOCKED", None}:
                checks.append({"checkId": "BROWSER.STATUS", "status": "failed", "observed": browser_launch_status, "expected": "PASS", "evidenceRefs": [str(prototype)]})
            if contract or scenario_results:
                runtime_scenario_checks, scenario_metrics = scenario_checks(scenario_results, args.required_state_kind)
                checks.extend(runtime_scenario_checks)
        except Exception as exc:
            checks.append({"checkId": "BROWSER.ADAPTER", "status": "failed", "observed": str(exc), "expected": "browser adapter completes", "evidenceRefs": [str(prototype)]})
    else:
        if contract:
            checks.extend(contract_checks)
        if args.require_real_browser:
            checks.append({"checkId": "BROWSER.REQUIRED", "status": "failed", "observed": "no browser runner configured", "expected": "real browser evidence", "evidenceRefs": [str(prototype)]})
        if scenario_results:
            if contract or scenario_results:
                runtime_scenario_checks, scenario_metrics = scenario_checks(scenario_results, args.required_state_kind)
                checks.extend(runtime_scenario_checks)
    if console_errors:
        checks.append({"checkId": "BROWSER.CONSOLE_ERRORS", "status": "failed", "observed": len(console_errors), "expected": 0, "evidenceRefs": [str(prototype)]})
    if page_errors:
        checks.append({"checkId": "BROWSER.PAGE_ERRORS", "status": "failed", "observed": len(page_errors), "expected": 0, "evidenceRefs": [str(prototype)]})
    if request_failures:
        checks.append({"checkId": "BROWSER.REQUEST_FAILURES", "status": "failed", "observed": len(request_failures), "expected": 0, "evidenceRefs": [str(prototype)]})
    failed = [item for item in checks if item["status"] == "failed"]
    status = "PASS" if not failed else "NEEDS_FIX"
    if browser_launch_status == "ENVIRONMENT_BLOCKED":
        status = "ENVIRONMENT_BLOCKED"
    elif args.require_real_browser and evidence_level != "REAL_BROWSER":
        status = "INSUFFICIENT"
    payload = {
        "schemaVersion": 2,
        "status": status,
        "executionMode": execution_mode,
        "runtimeEvidenceLevel": evidence_level,
        "browserVersion": browser_version,
        "prototypePath": str(prototype),
        "prototypeHash": prototype_hash,
        "contractId": contract_id,
        "workflowId": workflow_id,
        "prototypeRevision": prototype_revision,
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
        "requestFailures": request_failures,
        "screenshots": screenshots,
        "domSnapshots": dom_snapshots,
        "traces": traces,
        "scenarioResults": scenario_results,
        "scenarioMetrics": scenario_metrics,
        "interactionContract": str(args.interaction_contract.resolve()) if args.interaction_contract else None,
        "interactionManifest": str(args.interaction_manifest.resolve()) if args.interaction_manifest else None,
        "environmentError": environment_error,
        "checks": checks,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "executionMode": execution_mode, "runtimeEvidenceLevel": evidence_level, "scenarioMetrics": scenario_metrics, "out": str(args.out)}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
