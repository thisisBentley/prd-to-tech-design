#!/usr/bin/env python3
"""Run the local end-to-end gatekeeper after the multi-agent review chain.

Order:
1. Validate Delivery Gate Result v2 and sealed bundle.
2. Validate source provenance and cross-artifact preflight when a prototype exists.
3. Validate Tech Solution ledgers, decision closure, T1/R1 and architecture gates.
4. Run the deterministic multi-agent chain gatekeeper.
5. Emit a composite final-gatekeeper result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    parsed: Any = None
    for text in (proc.stdout, proc.stderr):
        text = text.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
            break
        except Exception:
            continue
    return {
        "command": cmd,
        "exitCode": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "result": parsed,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def one(pattern: str, base: Path) -> Path | None:
    matches = sorted(base.glob(pattern))
    return matches[0] if len(matches) == 1 else None


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_gate_result(delivery: Path, revision: str | None, gate: str) -> dict[str, Any] | None:
    root = delivery / ".delivery" / "gate-results"
    candidates = []
    if revision:
        candidates.append(root / revision / f"{gate}.json")
    candidates.extend(sorted(root.glob(f"*/{gate}.json"), key=lambda p: p.stat().st_mtime, reverse=True))
    for path in candidates:
        if path.exists():
            data = load_json(path)
            if data is not None:
                return data
    return None


def validate_artifact_profile_runtime(run_root: Path, delivery: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    state = load_json(delivery / ".delivery" / "state.json") or {}
    phase2 = state.get("phase2") or {}
    orchestration = load_json(run_root / ".agents" / "orchestration.json") or {}
    prototype_status = phase2.get("prototypeStatus") or orchestration.get("prototypeStatus")
    profile = phase2.get("artifactProfile") or orchestration.get("artifactProfile")
    prototype = one("*_Prototype.html", delivery)
    prototype_triggered = prototype is not None and prototype_status != "NOT_TRIGGERED" and profile not in {"PRD_ONLY", "EXTERNAL_UI_BOUNDARY"}

    if not prototype_triggered:
        for gate in ("U1", "U2"):
            result = latest_gate_result(delivery, phase2.get("revision"), gate)
            observed = (result or {}).get("result")
            ok = observed in {"NOT_APPLICABLE", "NOT_TRIGGERED"}
            checks.append({
                "checkId": f"FINAL.DELIVERY.{gate}.NOT_APPLICABLE",
                "status": "passed" if ok else "failed",
                "exitCode": 0 if ok else 2,
                "evidenceRefs": [str(delivery / ".delivery" / "gate-results")],
                "observed": observed or "missing",
                "expected": "NOT_APPLICABLE or NOT_TRIGGERED when Prototype is not triggered",
            })
        return checks

    runtime_files = sorted(
        [
            *(delivery / ".delivery" / "reviews").glob("**/runtime-result.json"),
            *(delivery / ".delivery").glob("prototype-runtime*.json"),
            *(run_root / ".agents" / "quality").glob("prototype-runtime*.json"),
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not runtime_files:
        checks.append({
            "checkId": "FINAL.DELIVERY.RUNTIME.AUTHORITY",
            "status": "failed",
            "exitCode": 2,
            "evidenceRefs": [str(prototype)],
            "observed": "no prototype runtime evidence",
            "expected": "REAL_BROWSER evidence bound to the current Prototype hash",
        })
        return checks

    runtime_path = runtime_files[0]
    data = load_json(runtime_path) or {}
    diagnostics = data.get("consoleDiagnostics") or data.get("consoleErrors") or []
    page_errors = data.get("pageErrors") or []
    request_failures = data.get("requestFailures") or []
    prototype_hash = hashlib.sha256(prototype.read_bytes()).hexdigest()
    runtime_level = data.get("runtimeEvidenceLevel")
    execution_mode = data.get("executionMode")
    hash_matches = data.get("prototypeHash") == prototype_hash
    clean = not diagnostics and not page_errors and not request_failures
    authoritative = (
        data.get("status") == "PASS"
        and runtime_level == "REAL_BROWSER"
        and execution_mode == "real-browser"
        and hash_matches
        and clean
    )
    checks.append({
        "checkId": "FINAL.DELIVERY.RUNTIME.AUTHORITY",
        "status": "passed" if authoritative else "failed",
        "exitCode": 0 if authoritative else 2,
        "evidenceRefs": [str(runtime_path), str(prototype)],
        "observed": {
            "status": data.get("status"),
            "runtimeEvidenceLevel": runtime_level,
            "executionMode": execution_mode,
            "prototypeHashMatches": hash_matches,
            "consoleDiagnostics": len(diagnostics),
            "pageErrors": len(page_errors),
            "requestFailures": len(request_failures),
        },
        "expected": "PASS + REAL_BROWSER + real-browser + matching Prototype hash + zero runtime errors",
    })
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--requirement-name", required=True)
    parser.add_argument("--skip-delivery", action="store_true")
    parser.add_argument("--skip-tech", action="store_true")
    parser.add_argument("--trust-kernel-run", type=Path, help="Require an M7.6-0 Trust Kernel READY decision before bundle finalization.")
    parser.add_argument("--allow-missing-trust-kernel", action="store_true", help="Legacy migration escape only; records an explicit waiver.")
    args = parser.parse_args()

    run_root = args.run_root.expanduser().resolve()
    delivery = run_root / "01-delivery"
    tech = run_root / "02-tech-solution"
    out_path = run_root / ".agents" / "final-gatekeeper.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    def add(check_id: str, result: dict[str, Any], evidence: list[str]) -> None:
        checks.append({
            "checkId": check_id,
            "status": "passed" if result["status"] == "PASS" else "failed",
            "exitCode": result["exitCode"],
            "evidenceRefs": evidence,
            "observed": (result.get("result") or {}).get("status") if isinstance(result.get("result"), dict) else result["status"],
            "expected": "PASS",
        })

    if args.trust_kernel_run and args.trust_kernel_run.is_file():
        checks.append({
            "checkId": "FINAL.TRUST_KERNEL.BINDING",
            "status": "passed",
            "evidenceRefs": [str(args.trust_kernel_run.resolve())],
            "observed": "trust-kernel run supplied",
            "expected": "READY trust-kernel run",
        })
    elif args.allow_missing_trust_kernel:
        checks.append({
            "checkId": "FINAL.TRUST_KERNEL.BINDING",
            "status": "failed",
            "evidenceRefs": [],
            "observed": "explicit legacy waiver; not production eligible",
            "expected": "READY trust-kernel run by default",
        })
    else:
        checks.append({
            "checkId": "FINAL.TRUST_KERNEL.BINDING",
            "status": "failed",
            "evidenceRefs": [],
            "observed": "missing trust-kernel run",
            "expected": "READY trust-kernel run by default",
        })

    if not args.skip_delivery:
        if not delivery.exists():
            add("FINAL.DELIVERY.PRESENT", {"status": "FAIL", "exitCode": 2, "result": None}, [str(delivery)])
        else:
            checks.extend(validate_artifact_profile_runtime(run_root, delivery))
            gate_files = sorted((delivery / ".delivery" / "gate-results").glob("*/*.json"))
            r = run([sys.executable, str(SCRIPTS / "gate_contract_validator.py"), "--json", *map(str, gate_files)])
            add("FINAL.DELIVERY.GATE_CONTRACT", r, [str(p) for p in gate_files])
            bundle_cmd = [sys.executable, str(SCRIPTS / "validate_delivery_bundle.py"), "--json", str(delivery)]
            if args.trust_kernel_run:
                bundle_cmd.extend(["--trust-kernel-run", str(args.trust_kernel_run.resolve())])
            r = run(bundle_cmd)
            add("FINAL.DELIVERY.BUNDLE", r, [str(delivery)])
            policy_lock = delivery / ".delivery" / "policy-lock.json"
            gate_dir = delivery / ".delivery" / "gate-results"
            revision = (load_json(delivery / ".delivery" / "final-seal.json") or {}).get("revision")
            configured_gate_dir = gate_dir / str(revision) if revision else gate_dir
            coverage_out = run_root / ".agents" / "gate-rule-coverage.json"
            if policy_lock.exists() and configured_gate_dir.exists():
                r = run([sys.executable, str(SCRIPTS / "validate_gate_rule_coverage.py"), "--policy-lock", str(policy_lock), "--gate-dir", str(configured_gate_dir), "--out", str(coverage_out)])
                add("FINAL.DELIVERY.RULE_COVERAGE", r, [str(policy_lock), str(configured_gate_dir), str(coverage_out)])
            else:
                checks.append({"checkId": "FINAL.DELIVERY.RULE_COVERAGE", "status": "failed", "evidenceRefs": [str(policy_lock), str(configured_gate_dir)], "observed": "policy lock or gate results missing", "expected": "all applicable gate rules are proven executed"})
            readiness_out = run_root / ".agents" / "delivery-readiness.json"
            r = run([sys.executable, str(SCRIPTS / "verify_delivery_bundle_integrity.py"), "--bundle", str(delivery), "--out", str(readiness_out)])
            add("FINAL.DELIVERY.READINESS", r, [str(readiness_out)])
            prd = one("*_PRD_DELIVERY.md", delivery)
            overview = one("*_Overview.html", delivery)
            prototype = one("*_Prototype.html", delivery)
            manifest = one("*prototype-manifest.json", delivery)
            if prototype:
                if manifest:
                    cmd = [sys.executable, str(SCRIPTS / "validate_prototype_binding.py"), "--prototype", str(prototype), "--manifest", str(manifest), "--json"]
                    if prd:
                        cmd.extend(["--prd", str(prd)])
                    r = run(cmd)
                    add("FINAL.DELIVERY.PROTOTYPE_BINDING", r, [str(prototype), str(manifest)])
                else:
                    checks.append({"checkId": "FINAL.DELIVERY.PROTOTYPE_BINDING", "status": "failed", "evidenceRefs": [str(prototype)], "observed": "prototype-manifest.json missing", "expected": "stable PRD/Prototype/AC machine binding"})
            if prd and overview:
                cmd = [sys.executable, str(SCRIPTS / "validate_source_provenance.py"), "--json", str(delivery), "--prd", str(prd), "--overview", str(overview)]
                if prototype:
                    cmd += ["--prototype", str(prototype)]
                r = run(cmd)
                add("FINAL.DELIVERY.PROVENANCE", r, [str(p) for p in [prd, overview, prototype] if p])
            else:
                add("FINAL.DELIVERY.PROVENANCE", {"status": "FAIL", "exitCode": 2, "result": None}, [str(delivery)])
            if prd and prototype:
                r = run([sys.executable, str(SCRIPTS / "check_cross_artifact_contracts.py"), "--prd", str(prd), "--prototype", str(prototype), "--json"])
                add("FINAL.DELIVERY.CROSS_ARTIFACT", r, [str(prd), str(prototype)])
            elif prd:
                checks.append({"checkId": "FINAL.DELIVERY.CROSS_ARTIFACT", "status": "passed", "evidenceRefs": [str(prd)], "observed": "prototype not triggered", "expected": "PASS or not triggered"})
            else:
                add("FINAL.DELIVERY.CROSS_ARTIFACT", {"status": "FAIL", "exitCode": 2, "result": None}, [str(delivery)])

    if not args.skip_tech:
        if not tech.exists():
            add("FINAL.TECH.PRESENT", {"status": "FAIL", "exitCode": 2, "result": None}, [str(tech)])
        else:
            r = run([sys.executable, str(SCRIPTS / "phase3.py"), "validate", "--run-root", str(run_root), "--requirement-name", args.requirement_name, "--require-ready"])
            add("FINAL.TECH.PHASE3", r, [str(tech)])

    domain_passed = bool(checks) and all(c["status"] == "passed" for c in checks)
    if domain_passed:
        r = run([sys.executable, str(SCRIPTS / "orchestrate.py"), "gatekeeper", "--run-root", str(run_root)])
        add("FINAL.AGENT.REVIEW_CHAIN", r, [str(run_root / ".agents" / "orchestration.json")])
    else:
        checks.append({
            "checkId": "FINAL.AGENT.REVIEW_CHAIN",
            "status": "failed",
            "exitCode": 2,
            "evidenceRefs": [str(run_root / ".agents" / "orchestration.json")],
            "observed": "skipped because domain gates failed",
            "expected": "run only after domain gates pass",
        })

    passed = bool(checks) and all(c["status"] == "passed" for c in checks)
    readiness_path = run_root / ".agents" / "delivery-readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8")) if readiness_path.exists() else {}
    result = {
        "schemaVersion": 1,
        "status": "READY" if passed else "FAIL",
        "runRoot": str(run_root),
        "requirementName": args.requirement_name,
        "contentReady": bool(readiness.get("contentReady")),
        "evidenceReady": bool(readiness.get("evidenceReady")),
        "bundleReady": bool(readiness.get("bundleReady")),
        "designReady": bool(readiness.get("designReady")),
        "checks": checks,
        "checkedAt": now(),
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
