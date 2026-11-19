#!/usr/bin/env python3
"""Real Chromium scenario runner using Playwright."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def state_value(page: Any, key: str) -> Any:
    return page.evaluate(
        """([key]) => {
          const read = (root, path) => path.split('.').reduce((value, part) => value == null ? undefined : value[part], root);
          let value = read(window.__AI_NATIVE_PROTOTYPE_STATE__ || {}, key);
          if (value !== undefined) return value;
          try {
            const stored = JSON.parse(localStorage.getItem('ai-native-prototype-state') || '{}');
            value = read(stored, key);
            if (value !== undefined) return value;
          } catch (_) {}
          value = read(window, key);
          return value === undefined ? null : value;
        }""",
        [key],
    )


def run_action(page: Any, action: dict[str, Any], checks: list[dict[str, Any]], scenario_id: str) -> bool:
    action_type = str(action.get("type", "")).strip().lower()
    selector = str(action.get("selector", "")).strip()
    value = str(action.get("value", ""))
    check_id = f"SCENARIO.{scenario_id}.{action_type}.{len(checks) + 1}"
    try:
        if action_type == "click":
            page.locator(selector).first.click(timeout=int(action.get("timeoutMs", 5000)))
        elif action_type == "fill":
            page.locator(selector).first.fill(value, timeout=int(action.get("timeoutMs", 5000)))
        elif action_type == "select":
            page.locator(selector).first.select_option(value, timeout=int(action.get("timeoutMs", 5000)))
        elif action_type == "press":
            page.locator(selector).first.press(value or "Enter", timeout=int(action.get("timeoutMs", 5000)))
        elif action_type == "wait":
            timeout = int(action.get("timeoutMs", 1000))
            page.wait_for_timeout(timeout)
        elif action_type == "assert-visible":
            page.locator(selector).first.wait_for(state="visible", timeout=int(action.get("timeoutMs", 5000)))
        elif action_type == "assert-text":
            expected = action.get("expected", value)
            locator = page.locator(selector).first if selector else page.locator("body")
            text = locator.inner_text(timeout=int(action.get("timeoutMs", 5000)))
            if str(expected) not in text:
                raise AssertionError(f"expected text {expected!r} in observed {text[:500]!r}")
        elif action_type == "assert-url":
            expected = str(action.get("expected", value))
            if expected not in page.url:
                raise AssertionError(f"expected URL fragment {expected!r} in {page.url!r}")
        elif action_type == "assert-hash":
            expected = str(action.get("expected", value)).lstrip("#")
            observed = page.url.split("#", 1)[1] if "#" in page.url else ""
            if expected != observed:
                raise AssertionError(f"expected hash {expected!r}, observed {observed!r}")
        elif action_type == "assert-state":
            key = str(action.get("stateKey") or action.get("selector") or "").strip()
            expected = action.get("expected", value)
            observed = state_value(page, key)
            if isinstance(expected, str) and isinstance(observed, str):
                matched = expected == observed
            else:
                matched = observed == expected or str(observed) == str(expected)
            if not matched:
                raise AssertionError(f"expected state {key}={expected!r}, observed {observed!r}")
        elif action_type == "eval":
            expression = str(action.get("value", ""))
            result = page.evaluate(expression)
            if action.get("expected") is not None and str(result) != str(action.get("expected")):
                raise AssertionError(f"eval result {result!r} != expected {action.get('expected')!r}")
        else:
            raise ValueError(f"unsupported action type: {action_type}")
        checks.append({"checkId": check_id, "status": "passed", "observed": "executed", "expected": action_type})
        return True
    except Exception as exc:
        checks.append({"checkId": check_id, "status": "failed", "observed": str(exc), "expected": action_type})
        return False


def body_haystack(page: Any) -> str:
    try:
        text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        text = ""
    try:
        attrs = page.locator("body *").evaluate_all(
            "els => els.flatMap(el => Array.from(el.attributes).map(a => `${a.name}=${a.value}`)).join(' ')"
        )
    except Exception:
        attrs = ""
    try:
        storage = page.evaluate("() => JSON.stringify(localStorage)")
    except Exception:
        storage = ""
    try:
        state = page.evaluate("() => JSON.stringify(window.__AI_NATIVE_PROTOTYPE_STATE__ || {})")
    except Exception:
        state = ""
    return " ".join([text or "", attrs or "", storage or "", state or "", page.url])


def contains_effect(haystack: str, value: str) -> bool:
    if not value:
        return False
    if value.startswith("!"):
        return value[1:] not in haystack
    return value in haystack


def evaluate_expected(page: Any, scenario: dict[str, Any], checks: list[dict[str, Any]]) -> bool:
    scenario_id = str(scenario.get("scenarioId", "unknown"))
    expected = scenario.get("expected") or {}
    haystack = body_haystack(page)
    ok = True
    view = str(expected.get("view", "")).strip()
    if view:
        passed = view in haystack
        checks.append({"checkId": f"SCENARIO.{scenario_id}.EXPECTED.VIEW", "status": "passed" if passed else "failed", "observed": view if passed else "missing", "expected": view})
        ok = ok and passed
    for kind, values in (("STATE", expected.get("states", [])), ("CONTEXT", expected.get("context", [])), ("DATA_EFFECT", expected.get("dataEffects", [])), ("FORBIDDEN_EFFECT", expected.get("forbiddenEffects", []))):
        for value in values or []:
            text = str(value)
            if kind == "FORBIDDEN_EFFECT":
                passed = text not in haystack
                expected_desc = f"must not contain {text}"
            else:
                passed = text in haystack
                expected_desc = f"must contain {text}"
            checks.append({"checkId": f"SCENARIO.{scenario_id}.EXPECTED.{kind}.{len(checks) + 1}", "status": "passed" if passed else "failed", "observed": "matched" if passed else "not matched", "expected": expected_desc})
            ok = ok and passed
    return ok


def run_scenario(page: Any, context: Any, scenario: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    scenario_id = str(scenario.get("scenarioId", "unknown"))
    role = str(scenario.get("role", "anonymous"))
    checks: list[dict[str, Any]] = []
    console_errors: list[dict[str, Any]] = []
    page_errors: list[str] = []
    request_failures: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    page.on("console", lambda message: console_errors.append({"scenarioId": scenario_id, "type": message.type, "text": message.text}) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("requestfailed", lambda request: request_failures.append({"scenarioId": scenario_id, "url": request.url, "failure": request.failure}))
    role_script = """
      window.__AI_NATIVE_ROLE__ = %s;
      try { localStorage.setItem('ai-native-role', window.__AI_NATIVE_ROLE__); } catch (_) {}
      try { localStorage.setItem('ai-native-prototype-state', JSON.stringify(%s)); } catch (_) {}
      window.__AI_NATIVE_PROTOTYPE_STATE__ = %s;
      document.addEventListener('DOMContentLoaded', () => {
        if (document.body) document.body.dataset.runtimeRole = window.__AI_NATIVE_ROLE__;
      });
    """ % (json.dumps(role), json.dumps(scenario.get("initialState", [])), json.dumps(scenario.get("initialState", [])))
    context.add_init_script(script=role_script)
    action_ok = True
    for action in scenario.get("setupActions", []) or []:
        action_ok = run_action(page, action, checks, scenario_id + ".SETUP") and action_ok
    for action in scenario.get("actions", []) or []:
        action_ok = run_action(page, action, checks, scenario_id) and action_ok
    expected_ok = evaluate_expected(page, scenario, checks)
    dom_path = evidence_dir / f"{scenario_id}.dom.html"
    screenshot_path = evidence_dir / f"{scenario_id}.png"
    trace_path = evidence_dir / f"{scenario_id}.trace.zip"
    try:
        dom_path.write_text(page.content(), encoding="utf-8")
        evidence_refs.append(str(dom_path))
    except Exception as exc:
        checks.append({"checkId": f"SCENARIO.{scenario_id}.DOM_SNAPSHOT", "status": "failed", "observed": str(exc), "expected": "DOM snapshot captured"})
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        evidence_refs.append(str(screenshot_path))
    except Exception as exc:
        checks.append({"checkId": f"SCENARIO.{scenario_id}.SCREENSHOT", "status": "failed", "observed": str(exc), "expected": "screenshot captured"})
    try:
        if context.tracing.is_tracing():
            context.tracing.stop(path=str(trace_path))
            evidence_refs.append(str(trace_path))
    except Exception as exc:
        checks.append({"checkId": f"SCENARIO.{scenario_id}.TRACE", "status": "failed", "observed": str(exc), "expected": "trace captured"})
    failed = [item["checkId"] for item in checks if item["status"] == "failed"]
    if console_errors:
        failed.append(f"SCENARIO.{scenario_id}.CONSOLE_ERRORS")
    if page_errors:
        failed.append(f"SCENARIO.{scenario_id}.PAGE_ERRORS")
    if request_failures:
        failed.append(f"SCENARIO.{scenario_id}.REQUEST_FAILURES")
    status = "PASS" if not failed and action_ok and expected_ok else "FAIL"
    return {
        "scenarioId": scenario_id,
        "status": status,
        "role": role,
        "checks": checks,
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
        "requestFailures": request_failures,
        "evidenceRefs": evidence_refs,
        "failedCheckIds": failed,
        "coveredStateKinds": [str(item) for item in (scenario.get("expected") or {}).get("states", []) or []],
    }


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(json.dumps({"status": "ENVIRONMENT_BLOCKED", "executionMode": "real-browser", "error": f"playwright unavailable: {exc}", "scenarioResults": [], "consoleErrors": [], "pageErrors": [], "requestFailures": [], "checks": []}, ensure_ascii=False))
        return 2
    request = json.load(sys.stdin)
    prototype = Path(request["prototypePath"]).resolve()
    scenarios = request.get("scenarios") or []
    evidence_dir = Path(request.get("evidenceDir") or prototype.parent / "runtime-evidence").resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    viewport = request.get("viewport") or {"width": 1440, "height": 900}
    executable_path = request.get("browserExecutablePath") or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    all_console: list[dict[str, Any]] = []
    all_page: list[str] = []
    all_requests: list[dict[str, Any]] = []
    scenario_results: list[dict[str, Any]] = []
    browser_version = None
    launch_error = None
    try:
        with sync_playwright() as playwright:
            launch_args: dict[str, Any] = {"headless": True}
            if executable_path:
                launch_args["executable_path"] = str(executable_path)
            browser = playwright.chromium.launch(**launch_args)
            browser_version = browser.version
            if not scenarios:
                scenario_results.append({
                    "scenarioId": "NO_RUNTIME_SCENARIOS",
                    "status": "FAIL",
                    "role": "unknown",
                    "checks": [{"checkId": "RUNTIME.SCENARIOS", "status": "failed", "observed": 0, "expected": ">=1"}],
                    "consoleErrors": [],
                    "pageErrors": [],
                    "requestFailures": [],
                    "evidenceRefs": [str(prototype)],
                    "failedCheckIds": ["RUNTIME.SCENARIOS"],
                })
            for scenario in scenarios:
                context = browser.new_context(viewport=viewport)
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                result = run_scenario(page, context, scenario, evidence_dir)
                scenario_results.append(result)
                all_console.extend(result["consoleErrors"])
                all_page.extend(result["pageErrors"])
                all_requests.extend(result["requestFailures"])
                context.close()
            browser.close()
    except Exception as exc:
        launch_error = str(exc)
    checked_at = now()
    if launch_error:
        payload = {
            "schemaVersion": 1,
            "status": "ENVIRONMENT_BLOCKED",
            "executionMode": "real-browser",
            "browserVersion": browser_version,
            "error": launch_error,
            "scenarioResults": scenario_results,
            "consoleErrors": all_console,
            "pageErrors": all_page,
            "requestFailures": all_requests,
            "checks": [{"checkId": "BROWSER.LAUNCH", "status": "failed", "observed": launch_error, "expected": "Chromium launches"}],
            "checkedAt": checked_at,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 2
    failed = [item for item in scenario_results if item["status"] != "PASS"]
    status = "PASS" if not failed and not all_console and not all_page and not all_requests else "FAIL"
    covered = set()
    for result in scenario_results:
        for check in result["checks"]:
            if check["status"] == "passed" and ".EXPECTED.STATE." in check["checkId"]:
                covered.add(check["checkId"].split(".EXPECTED.STATE.", 1)[0])
    payload = {
        "schemaVersion": 1,
        "status": status,
        "executionMode": "real-browser",
        "browserVersion": browser_version,
        "scenarioResults": scenario_results,
        "scenarioMetrics": {
            "total": len(scenario_results),
            "passed": sum(1 for item in scenario_results if item["status"] == "PASS"),
            "failed": sum(1 for item in scenario_results if item["status"] == "FAIL"),
            "skipped": sum(1 for item in scenario_results if item["status"] == "SKIPPED"),
            "coveredStateKinds": sorted(covered),
        },
        "consoleErrors": all_console,
        "pageErrors": all_page,
        "requestFailures": all_requests,
        "checks": [check for result in scenario_results for check in result["checks"]],
        "checkedAt": checked_at,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
