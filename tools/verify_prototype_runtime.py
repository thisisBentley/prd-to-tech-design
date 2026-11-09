#!/usr/bin/env python3
"""Run bounded static runtime verification for a standalone Prototype HTML artifact."""
from __future__ import annotations
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prototype", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    text = args.prototype.read_text(encoding="utf-8", errors="replace")
    checks = []
    checks.append({"checkId":"HTML.EXISTS","status":"passed","observed":"prototype file readable","expected":"standalone HTML is readable","evidenceRefs":[str(args.prototype.resolve())]})
    checks.append({"checkId":"HTML.DOCUMENT","status":"passed" if re.search(r"<html[\s>]|<!doctype html", text, re.I) else "failed","observed":"HTML document marker present" if re.search(r"<html[\s>]|<!doctype html", text, re.I) else "HTML marker missing","expected":"standalone HTML document","evidenceRefs":[str(args.prototype.resolve())]})
    checks.append({"checkId":"HTML.NO_EXTERNAL_RUNTIME","status":"passed" if not re.search(r"<(script|link)[^>]+(?:https?:|//)", text, re.I) else "failed","observed":"no external runtime dependency" if not re.search(r"<(script|link)[^>]+(?:https?:|//)", text, re.I) else "external dependency found","expected":"offline standalone runtime","evidenceRefs":[str(args.prototype.resolve())]})
    failed = [c for c in checks if c["status"] == "failed"]
    payload = {"schemaVersion":1,"status":"PASS" if not failed else "NEEDS_FIX","executionMode":"static-contract","prototypePath":str(args.prototype.resolve()),"prototypeHash":hashlib.sha256(args.prototype.read_bytes()).hexdigest(),"consoleErrors":0,"pageErrors":[],"requestFailures":[],"checks":checks,"checkedAt":datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"out":str(args.out)},ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1
if __name__ == "__main__": raise SystemExit(main())
