#!/usr/bin/env python3
"""Build a read-only Collaboration Surface from a Project Episode."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from collaboration_surface import build, render_markdown, save


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--decision-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    try:
        surface = build(episode_path=args.episode.resolve(), review_dir=args.review_dir.resolve(), decision_dir=args.decision_dir.resolve())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    save(args.out.resolve(), surface)
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(render_markdown(surface), encoding="utf-8")
    print(json.dumps({
        "status": surface["status"],
        "surfaceId": surface["surfaceId"],
        "nextActions": surface["metrics"]["nextActions"],
        "out": str(args.out.resolve()),
        "markdown": str(args.markdown_out.resolve()) if args.markdown_out else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
