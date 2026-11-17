#!/usr/bin/env python3
"""Resolve producer declaration and audit evidence references to frozen artifacts."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"
LINE_RANGE_RE = re.compile(r"^L(\d+)(?:-L?(\d+))?$", re.IGNORECASE)
URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def evidence_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}: return "MARKDOWN"
    if suffix in {".html", ".htm"}: return "HTML"
    if suffix == ".json": return "JSON"
    if suffix in {".log"}: return "LOG"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}: return "IMAGE"
    if suffix in {".xml", ".svg"}: return "XML"
    if suffix in {".txt", ".csv", ".yaml", ".yml"}: return "TEXT"
    if suffix in {".xmind", ".zip", ".pdf"}: return "BINARY"
    return "UNKNOWN"


def slugify(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value).strip().lower()
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-")


def json_pointer(value: Any, pointer: str) -> tuple[bool, Any]:
    if pointer == "": return True, value
    if not pointer.startswith("/"): return False, None
    current = value
    for pointer_part in pointer.split("/")[1:]:
        pointer_part = pointer_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try: current = current[int(pointer_part)]
            except (ValueError, IndexError): return False, None
        elif isinstance(current, dict) and pointer_part in current:
            current = current[pointer_part]
        else:
            return False, None
    return True, current


def resolve_fragment(path: Path, fragment: str) -> tuple[bool, str, str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not fragment:
        return True, "NONE", text[:500], text
    line_match = LINE_RANGE_RE.fullmatch(fragment)
    if line_match:
        lines = text.splitlines()
        start = int(line_match.group(1))
        end = int(line_match.group(2) or start)
        if start < 1 or end < start or end > len(lines):
            return False, "LINE_RANGE", "", f"line range {start}-{end} outside 1-{len(lines)}"
        excerpt = "\n".join(lines[start - 1:end])
        return True, "LINE_RANGE", excerpt, excerpt
    if path.suffix.lower() == ".json" and fragment.startswith("/"):
        try:
            payload = json.loads(text)
        except Exception as exc:
            return False, "JSON_POINTER", "", f"invalid JSON: {exc}"
        found, value = json_pointer(payload, fragment)
        if not found:
            return False, "JSON_POINTER", "", f"JSON pointer not found: {fragment}"
        excerpt = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return True, "JSON_POINTER", excerpt[:1000], excerpt
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        target = fragment.lower().lstrip("#")
        for line in text.splitlines():
            heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if heading and (heading.group(1).strip().lower() == target or slugify(heading.group(1)) == slugify(target) or target in heading.group(1).lower()):
                return True, "MARKDOWN_HEADING", line, line
    if suffix in {".html", ".htm", ".svg", ".xml"}:
        target = fragment.lstrip("#")
        pattern = re.compile(r"(?:data-ai-id|id|name)\s*=\s*[\"']" + re.escape(target) + r"[\"']", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            start = max(0, text.rfind("<", 0, match.start()))
            end = text.find(">", match.end())
            excerpt = text[start:end + 1 if end >= 0 else match.end()]
            return True, "HTML_ANCHOR", excerpt, excerpt
    decoded = fragment.replace("%20", " ")
    if decoded and decoded in text:
        index = text.index(decoded)
        return True, "TEXT_EXCERPT", text[max(0, index - 120): index + len(decoded) + 240], decoded
    return False, "TEXT_EXCERPT", "", f"fragment not found in {path.name}: {fragment}"


def resolve_ref(reference: str, roots: list[Path]) -> dict[str, Any]:
    result = {"reference": reference, "status": "unresolved", "evidenceType": "UNKNOWN", "fragmentType": "NONE", "message": ""}
    if URL_RE.match(reference) and not reference.startswith("file://"):
        result["fragmentType"] = "UNSUPPORTED_SCHEME"
        result["message"] = "non-file URI cannot be resolved as frozen artifact evidence"
        return result
    base, separator, fragment = reference.partition("#")
    if reference.startswith("file://"):
        base = reference.removeprefix("file://").split("#", 1)[0]
        separator = "#" if "#" in reference else ""
        fragment = reference.split("#", 1)[1] if "#" in reference else ""
    if not base:
        result["message"] = "evidence reference has no file path"
        return result
    path = Path(base)
    candidate: Path | None = None
    if path.is_absolute():
        candidate = path.resolve()
    else:
        for root in roots:
            possible = (root / path).resolve()
            if possible.is_file():
                candidate = possible
                break
    if candidate is None or not candidate.is_file():
        result["message"] = f"file not found: {base}"
        return result
    if not any(_is_relative_to(candidate, root.resolve()) for root in roots):
        result["message"] = f"evidence path escapes allowed roots: {candidate}"
        return result
    result["resolvedPath"] = str(candidate)
    result["evidenceType"] = evidence_type(candidate)
    ok, fragment_type, excerpt, full_or_message = resolve_fragment(candidate, fragment if separator else "")
    result["fragmentType"] = fragment_type
    if not ok:
        result["message"] = full_or_message
        return result
    result["status"] = "resolved"
    result["excerptSha256"] = digest_bytes(excerpt.encode())
    result["message"] = "resolved" + (f" via {fragment_type}" if fragment else "")
    return result


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check(check_id: str, passed: bool, observed: Any, expected: str, refs: list[str]) -> dict[str, Any]:
    return {"checkId": check_id, "status": "passed" if passed else "failed", "observed": observed, "expected": expected, "evidenceRefs": refs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--result", action="append", type=Path, default=[])
    parser.add_argument("--declarations", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    artifact_root = args.artifact_root.resolve()
    plan_path = args.plan.resolve()
    plan = load(plan_path)
    results: list[tuple[Path, dict[str, Any]]] = []
    search_dirs = [artifact_root]
    if args.declarations:
        search_dirs.append(args.declarations.resolve().parent)
    for path in sorted((args.results_dir.resolve().glob("*.result.json") if args.results_dir else [])):
        try: results.append((path.resolve(), load(path)))
        except Exception: continue
    for path in args.result:
        try: results.append((path.resolve(), load(path.resolve())))
        except Exception: continue
    resolutions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    declarations_count = 0

    expected_jobs = {job["jobId"]: job for job in plan.get("jobs", [])}
    results_by_job = {str(result.get("jobId")): (path, result) for path, result in results}
    missing_jobs = sorted(set(expected_jobs) - set(results_by_job))
    checks.append(check("PLAN.AUDIT_RESULTS", not missing_jobs, {"missingJobs": missing_jobs}, "every audit job has a result", [str(plan_path)]))
    if missing_jobs:
        findings.append({"findingId": "EVR-PLAN-JOBS", "severity": "BLOCKING", "code": "MISSING_AUDIT_RESULT", "message": "missing audit results: " + ", ".join(missing_jobs), "evidenceRefs": [str(plan_path)]})

    audit_checks = 0
    for job_id, (path, result) in sorted(results_by_job.items()):
        job = expected_jobs.get(job_id, {})
        for item in result.get("checks", []):
            audit_checks += 1
            refs = [str(value) for value in item.get("evidenceRefs", []) if str(value).strip()]
            observed = str(item.get("observed", "")).strip()
            expected = str(item.get("expected", "")).strip()
            non_vacuous = bool(refs) and bool(observed) and observed != expected and observed not in {job_id, *(job.get("sourcePolicyRuleIds") or [])}
            checks.append(check(f"AUDIT.OBSERVATION.{job_id}.{item.get('checkId')}", non_vacuous, {"observed": observed, "expected": expected, "refs": len(refs)}, "PASS evidence has a non-empty, non-rule-repeating observation and evidence refs", [str(path)]))
            if not non_vacuous:
                findings.append({"findingId": f"EVR-AUD-{len(findings)+1:04d}", "severity": "BLOCKING", "code": "VACUOUS_AUDIT_EVIDENCE", "message": f"{job_id}/{item.get('checkId')} has vacuous evidence", "evidenceRefs": [str(path)]})
            if item.get("status") != "passed":
                continue
            for ref in refs:
                resolution = resolve_ref(ref, search_dirs)
                resolution.update({"source": "AUDIT_RESULT", "jobId": job_id, "checkId": str(item.get("checkId")), "ruleIds": list(item.get("policyRuleIds") or [])})
                resolutions.append(resolution)
                if resolution["status"] != "resolved":
                    findings.append({"findingId": f"EVR-REF-{len(findings)+1:04d}", "severity": "BLOCKING", "code": "UNRESOLVED_AUDIT_EVIDENCE", "message": f"{job_id}/{item.get('checkId')}: {resolution['message']}", "evidenceRefs": [ref, str(path)]})

    if args.declarations and args.declarations.is_file():
        declarations = load(args.declarations.resolve())
        declaration_roots = [artifact_root, args.declarations.resolve().parent]
        for declaration in declarations.get("declarations", []):
            declarations_count += 1
            obligation_id = str(declaration.get("obligationId", ""))
            refs = [str(value) for value in declaration.get("evidenceRefs", []) if str(value).strip()]
            artifact = str(declaration.get("artifact", "")).strip()
            location = str(declaration.get("location", "")).strip()
            local_refs = list(refs)
            if artifact:
                local_refs.insert(0, artifact + (location if location.startswith("#") else (("#" + location) if location and "#" not in location else "")))
            for ref in local_refs:
                resolution = resolve_ref(ref, declaration_roots)
                resolution.update({"source": "PRODUCER_DECLARATION", "ruleIds": [str(declaration.get("ruleId", ""))] if declaration.get("ruleId") else []})
                resolutions.append(resolution)
                if resolution["status"] != "resolved":
                    findings.append({"findingId": f"EVR-DECL-{len(findings)+1:04d}", "severity": "BLOCKING", "code": "UNRESOLVED_DECLARATION_EVIDENCE", "message": f"{obligation_id}: {resolution['message']}", "evidenceRefs": [ref, str(args.declarations.resolve())]})

    resolved_count = sum(1 for item in resolutions if item["status"] == "resolved")
    unresolved_count = len(resolutions) - resolved_count
    status = "PASS" if not findings and not missing_jobs else "FAIL"
    report = {
        "schemaVersion": 1,
        "reportId": f"evidence-resolution-{plan.get('workflowId')}-{plan.get('revision')}",
        "workflowId": plan.get("workflowId"),
        "revision": plan.get("revision"),
        "status": status,
        "artifactRoot": str(artifact_root),
        "checks": checks,
        "resolutions": resolutions,
        "findings": findings,
        "metrics": {"references": len(resolutions), "resolved": resolved_count, "unresolved": unresolved_count, "declarations": declarations_count, "auditChecks": audit_checks},
        "checkedAt": now(),
    }
    schema = load(SCHEMA_ROOT / "evidence-resolution-report.schema.json")
    schema_errors = validate(report, schema, schema)
    if schema_errors:
        report["status"] = "FAIL"
        report["findings"].extend({"findingId": f"EVR-SCHEMA-{index}", "severity": "BLOCKING", "code": "SCHEMA_ERROR", "message": item, "evidenceRefs": [str(args.out)]} for index, item in enumerate(schema_errors, start=1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "references": len(resolutions), "unresolved": unresolved_count, "findings": len(report["findings"]), "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
