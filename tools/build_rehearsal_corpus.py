#!/usr/bin/env python3
"""Build a deterministic Rehearsal Corpus from gate and observed-failure evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rehearsal_corpus import build, render_markdown, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--finding-ledger", type=Path, required=True)
    parser.add_argument("--audit-results-dir", type=Path, required=True)
    parser.add_argument("--tool-failure-report", type=Path)
    parser.add_argument("--manual-scenarios", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    try:
        corpus = build(
            workflow_id=args.workflow_id,
            revision=args.revision,
            gate_policy_path=args.gate_policy.resolve(),
            finding_ledger_path=args.finding_ledger.resolve(),
            audit_results_dir=args.audit_results_dir.resolve(),
            tool_failure_path=args.tool_failure_report.resolve() if args.tool_failure_report else None,
            manual_scenarios_path=args.manual_scenarios.resolve() if args.manual_scenarios else None,
        )
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), corpus)
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(render_markdown(corpus), encoding="utf-8")
    print(json.dumps({
        "status": corpus["status"],
        "corpusId": corpus["corpusId"],
        "scenarios": corpus["metrics"]["scenarioCount"],
        "out": str(args.out.resolve()),
        "markdown": str(args.markdown_out.resolve()) if args.markdown_out else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
