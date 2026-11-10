#!/usr/bin/env python3
"""Verify a standalone Prototype through a real browser adapter or a static fallback."""
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


def static_checks(prototype: Path) -> list[dict[str, Any]]:
    text = prototype.read_text(encoding="utf-8", errors="replace")
    return [
        {"checkId": "HTML.EXISTS", "status": "passed", "observed": "prototype file readable", "expected": "standalone HTML is readable", "evidenceRefs": [str(prototype.resolve())]},
        {"checkId": "HTML.DOCUMENT", "status": "passed" if re.search(r"<html[\s>]|<!doctype html", text, re.I) else "failed", "observed": "HTML document marker present" if re.search(r"<html[\s>]|<!doctype html", text, re.I) else "HTML marker missing", "expected": "standalone HTML document", "evidenceRefs": [str(prototype.resolve())]},
        {"checkId": "HTML.NO_EXTERNAL_RUNTIME", "status": "passed" if not re.search(r"<(script|link)[^>]+(?:https?:|//)", text, re.I) else "failed", "observed": "no external runtime dependency" if not re.search(r"<(script|link)[^>]+(?:https?:|//)", text, re.I) else "external dependency found", "expected": "offline standalone runtime", "evidenceRefs": [str(prototype.resolve())]},
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser-runner", nargs="+", help="Command that reads a JSON request from stdin and returns browser evidence JSON.")
    parser.add_argument("--browser-timeout", type=float, default=30)
    parser.add_argument("--require-real-browser", action="store_true")
    parser.add_argument("--interaction-manifest", type=Path)
    args = parser.parse_args()
    prototype = args.prototype.resolve()
    prototype_hash = hashlib.sha256(prototype.read_bytes()).hexdigest()
    static = static_checks(prototype)
    checks = list(static)
    evidence_level = "STATIC_CONTRACT"
    execution_mode = "static-contract"
    browser_version = None
    screenshots: list[str] = []
    traces: list[str] = []
    console_errors: list[dict[str, Any] | str] = []
    page_errors: list[Any] = []
    request_failures: list[Any] = []
    interaction_manifest = load(args.interaction_manifest) if args.interaction_manifest else None

    if args.browser_runner:
        request = {
            "schemaVersion": 1,
            "prototypePath": str(prototype),
            "prototypeHash": prototype_hash,
            "interactionManifest": interaction_manifest,
            "viewport": {"width": 1440, "height": 900},
        }
        try:
            browser = run_browser_adapter(args.browser_runner, request, args.browser_timeout)
            execution_mode = str(browser.get("executionMode", "real-browser"))
            evidence_level = "REAL_BROWSER" if execution_mode == "real-browser" else "BROWSER_ADAPTER"
            browser_version = browser.get("browserVersion")
            screenshots = [str(item) for item in browser.get("screenshots", [])]
            traces = [str(item) for item in browser.get("traces", [])]
            console_errors = browser.get("consoleErrors", []) or []
            page_errors = browser.get("pageErrors", []) or []
            request_failures = browser.get("requestFailures", []) or []
            browser_checks = browser.get("checks", [])
            if isinstance(browser_checks, list):
                checks.extend(browser_checks)
            if browser.get("returnCode") != 0:
                checks.append({"checkId": "BROWSER.RUNNER", "status": "failed", "observed": f"returnCode={browser.get('returnCode')}", "expected": "zero", "evidenceRefs": [str(prototype)]})
            if browser.get("status") not in {"PASS", None}:
                checks.append({"checkId": "BROWSER.STATUS", "status": "failed", "observed": browser.get("status"), "expected": "PASS", "evidenceRefs": [str(prototype)]})
        except Exception as exc:
            checks.append({"checkId": "BROWSER.ADAPTER", "status": "failed", "observed": str(exc), "expected": "browser adapter completes", "evidenceRefs": [str(prototype)]})
    elif args.require_real_browser:
        checks.append({"checkId": "BROWSER.REQUIRED", "status": "failed", "observed": "no browser runner configured", "expected": "real browser evidence", "evidenceRefs": [str(prototype)]})

    if console_errors:
        checks.append({"checkId": "BROWSER.CONSOLE_ERRORS", "status": "failed", "observed": len(console_errors), "expected": 0, "evidenceRefs": [str(prototype)]})
    if page_errors:
        checks.append({"checkId": "BROWSER.PAGE_ERRORS", "status": "failed", "observed": len(page_errors), "expected": 0, "evidenceRefs": [str(prototype)]})
    if request_failures:
        checks.append({"checkId": "BROWSER.REQUEST_FAILURES", "status": "failed", "observed": len(request_failures), "expected": 0, "evidenceRefs": [str(prototype)]})
    failed = [item for item in checks if item["status"] == "failed"]
    status = "PASS" if not failed else "NEEDS_FIX"
    if args.require_real_browser and evidence_level != "REAL_BROWSER":
        status = "INSUFFICIENT"
    payload = {
        "schemaVersion": 2,
        "status": status,
        "executionMode": execution_mode,
        "runtimeEvidenceLevel": evidence_level,
        "browserVersion": browser_version,
        "prototypePath": str(prototype),
        "prototypeHash": prototype_hash,
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
        "requestFailures": request_failures,
        "screenshots": screenshots,
        "traces": traces,
        "interactionManifest": str(args.interaction_manifest.resolve()) if args.interaction_manifest else None,
        "checks": checks,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "executionMode": execution_mode, "runtimeEvidenceLevel": evidence_level, "out": str(args.out)}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
