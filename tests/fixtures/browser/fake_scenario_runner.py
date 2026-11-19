#!/usr/bin/env python3
"""Fixture-only browser adapter used to test scenario plumbing without Chromium."""
from __future__ import annotations

import json
import sys

request = json.load(sys.stdin)
results = []
for scenario in request.get("scenarios", []):
    states = [str(item) for item in scenario.get("expected", {}).get("states", [])]
    results.append({
        "scenarioId": scenario["scenarioId"],
        "status": "PASS",
        "role": scenario.get("role", "anonymous"),
        "checks": [{"checkId": "FIXTURE.SCENARIO", "status": "passed", "observed": "executed", "expected": "executed"}],
        "consoleErrors": [],
        "pageErrors": [],
        "requestFailures": [],
        "evidenceRefs": [],
        "failedCheckIds": [],
        "coveredStateKinds": states,
    })
print(json.dumps({
    "status": "PASS",
    "executionMode": "browser-adapter",
    "browserVersion": "fixture-adapter",
    "scenarioResults": results,
    "consoleErrors": [],
    "pageErrors": [],
    "requestFailures": [],
    "checks": [],
}))
