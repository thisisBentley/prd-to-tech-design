#!/usr/bin/env python3
"""Attach workflow/revision-bound execution metrics to a Finding snapshot."""
from __future__ import annotations

import argparse
from pathlib import Path

from semantic_convergence import load, now, save, validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--availability", choices=["COMPLETE", "PARTIAL", "UNAVAILABLE"], required=True)
    parser.add_argument("--repair-rounds", type=int, required=True)
    parser.add_argument("--elapsed-ms", type=float)
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--context-object-count", type=int)
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--unavailable-reason")
    args = parser.parse_args()
    snapshot = load(args.snapshot.resolve())
    total_tokens = None
    if args.input_tokens is not None and args.output_tokens is not None:
        total_tokens = args.input_tokens + args.output_tokens
    snapshot["executionMetrics"] = {
        "availability": args.availability,
        "elapsedMs": args.elapsed_ms,
        "inputTokens": args.input_tokens,
        "outputTokens": args.output_tokens,
        "totalTokens": total_tokens,
        "repairRounds": args.repair_rounds,
        "contextObjectCount": args.context_object_count,
        "sourceRefs": args.source_ref,
        "capturedAt": now(),
    }
    if args.unavailable_reason:
        snapshot["executionMetrics"]["unavailableReason"] = args.unavailable_reason
    errors = validate_schema_value(snapshot, "convergence-finding-snapshot.schema.json")
    if errors:
        raise SystemExit("; ".join(errors))
    save(args.out, snapshot)
    print(f"PASS {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
