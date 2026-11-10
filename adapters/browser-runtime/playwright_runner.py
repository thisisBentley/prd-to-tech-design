#!/usr/bin/env python3
"""Real Chromium runtime adapter using Playwright."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "executionMode": "real-browser", "error": f"playwright unavailable: {exc}", "consoleErrors": [], "pageErrors": [], "requestFailures": [], "checks": []}, ensure_ascii=False))
        return 2
    request = json.load(sys.stdin)
    prototype = Path(request["prototypePath"]).resolve()
    interaction_manifest = request.get("interactionManifest") or {}
    console_errors = []
    page_errors = []
    request_failures = []
    checks = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda message: console_errors.append({"type": message.type, "text": message.text}) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: request_failures.append({"url": request.url, "failure": request.failure}))
        page.goto(prototype.as_uri(), wait_until="networkidle", timeout=15000)
        checks.append({"checkId": "BROWSER.LOAD", "status": "passed", "observed": "loaded", "expected": "loaded", "evidenceRefs": [str(prototype)]})
        for action in interaction_manifest.get("actions", []) if isinstance(interaction_manifest, dict) else []:
            action_type = action.get("type")
            selector = action.get("selector")
            if action_type == "click" and selector:
                page.locator(selector).first.click(timeout=5000)
                checks.append({"checkId": f"BROWSER.CLICK.{selector}", "status": "passed", "observed": "clicked", "expected": "clicked", "evidenceRefs": [str(prototype)]})
        browser_version = browser.version
        browser.close()
    status = "PASS" if not console_errors and not page_errors and not request_failures else "FAIL"
    print(json.dumps({"status": status, "executionMode": "real-browser", "browserVersion": browser_version, "consoleErrors": console_errors, "pageErrors": page_errors, "requestFailures": request_failures, "checks": checks}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
