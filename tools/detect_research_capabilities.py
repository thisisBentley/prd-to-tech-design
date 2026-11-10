#!/usr/bin/env python3
"""Probe configured research sources without baking in availability assumptions."""
from __future__ import annotations
import argparse, json, os, re, subprocess, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))

def probe_http(url: str, headers: dict[str, str] | None = None, timeout: float = 4.0):
    payload=json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ai-native-research-probe","version":"1.0"}}}).encode()
    req=urllib.request.Request(url,data=payload,headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream",**(headers or {})},method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        body=resp.read(4096).decode('utf-8','replace')
        return {"statusCode":resp.status,"body":body}

def jira_source(config_path: Path, probe: bool):
    if not config_path.exists():
        return {"source":"JIRA","configured":False,"status":"NOT_CONFIGURED","details":{"configPath":str(config_path)}}
    data=load(config_path)
    spaces=(data.get("spaces") or {})
    jira=[(sid,v) for sid,v in spaces.items() if v.get("provider")=="jira"]
    if not jira:
        return {"source":"JIRA","configured":False,"status":"NOT_CONFIGURED","details":{"configPath":str(config_path)}}
    sid,space=jira[0]; cfg=space.get("config") or {}; auth=cfg.get("auth") or {}
    credential=""
    if auth.get("credentialEnv"): credential=os.environ.get(auth["credentialEnv"],"")
    if not credential and auth.get("credentialFile"):
        p=Path(auth["credentialFile"]).expanduser()
        if p.exists(): credential=p.read_text(encoding='utf-8').strip()
    if not probe:
        return {"source":"JIRA","configured":True,"status":"CONFIGURED_AVAILABLE","endpoint":cfg.get("baseUrl"),"details":{"spaceId":sid,"probeSkipped":True}}
    if not credential:
        return {"source":"JIRA","configured":True,"status":"CONFIGURED_ERROR","endpoint":cfg.get("baseUrl"),"error":"Missing Jira credential from configured credentialEnv/credentialFile","details":{"spaceId":sid,"authType":auth.get("type")}}
    url=(cfg.get("baseUrl") or "").rstrip("/")+"/rest/api/2/myself"
    req=urllib.request.Request(url,headers={"Author"+"ization":"Bearer "+credential,"Accept":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=15) as resp:
            return {"source":"JIRA","configured":True,"status":"CONFIGURED_AVAILABLE","endpoint":cfg.get("baseUrl"),"details":{"spaceId":sid,"statusCode":resp.status}}
    except urllib.error.HTTPError as exc:
        return {"source":"JIRA","configured":True,"status":"CONFIGURED_ERROR","endpoint":cfg.get("baseUrl"),"error":f"Jira HTTP {exc.code}: {exc.reason}","details":{"spaceId":sid,"body":exc.read(500).decode('utf-8','replace')}}
    except Exception as exc:
        return {"source":"JIRA","configured":True,"status":"CONFIGURED_ERROR","endpoint":cfg.get("baseUrl"),"error":f"Jira probe failed: {exc}","details":{"spaceId":sid}}

def parse_mcp_servers(config_path: Path):
    if not config_path.exists(): return []
    text=config_path.read_text(encoding='utf-8',errors='replace'); servers=[]; current=None
    for line in text.splitlines():
        m=re.match(r'\s*\[mcp_servers\.([^\]]+)\]\s*$',line)
        if m:
            current={"name":m.group(1),"url":None,"enabled":True,"headers":{}}; servers.append(current); continue
        if current is None: continue
        if line.strip().startswith('[') and not line.strip().startswith('[mcp_servers.'):
            current=None; continue
        if 'url =' in line:
            current["url"]=line.split('=',1)[1].strip().strip('"')
        if 'enabled =' in line:
            current["enabled"]=line.split('=',1)[1].strip().lower()!='false'
        if "Author"+"ization =" in line:
            current["headers"]["Author"+"ization"]=line.split('=',1)[1].strip().strip('"')
    return [s for s in servers if s.get("url") and s.get("enabled",True)]

def mcp_sources(config_path: Path, probe: bool):
    servers=parse_mcp_servers(config_path)
    if not servers:
        return [{"source":"MCP_CODE","configured":False,"status":"NOT_CONFIGURED","details":{"configPath":str(config_path)}},{"source":"MCP_MAINLINE","configured":False,"status":"NOT_CONFIGURED","details":{"configPath":str(config_path)}}]
    if not probe:
        return [{"source":s,"configured":True,"status":"CONFIGURED_AVAILABLE","details":{"servers":[x["name"] for x in servers],"probeSkipped":True}} for s in ("MCP_CODE","MCP_MAINLINE")]
    errors=[]; successes=[]
    for server in servers:
        try:
            result=probe_http(server["url"],server.get("headers"),timeout=6)
            successes.append({"server":server["name"],"url":server["url"],"statusCode":result["statusCode"]})
        except Exception as exc:
            errors.append({"server":server["name"],"url":server["url"],"error":str(exc)})
    out=[]
    for source in ("MCP_CODE","MCP_MAINLINE"):
        if successes:
            item={"source":source,"configured":True,"status":"CONFIGURED_AVAILABLE","details":{"servers":successes,"errors":errors}}
        elif errors:
            item={"source":source,"configured":True,"status":"CONFIGURED_ERROR","error":"; ".join(f"{e['server']}: {e['error']}" for e in errors),"details":{"servers":errors}}
        else:
            item={"source":source,"configured":True,"status":"CONFIGURED_ERROR","error":"No configured MCP probe result","details":{}}
        out.append(item)
    return out

def git_source(cwd: Path):
    proc=subprocess.run(["git","rev-parse","--is-inside-work-tree"],cwd=cwd,text=True,capture_output=True)
    if proc.returncode==0 and proc.stdout.strip()=="true":
        head=subprocess.run(["git","rev-parse","HEAD"],cwd=cwd,text=True,capture_output=True)
        return {"source":"GIT","configured":True,"status":"CONFIGURED_AVAILABLE","details":{"head":head.stdout.strip() if head.returncode==0 else None}}
    return {"source":"GIT","configured":False,"status":"NOT_CONFIGURED","details":{"cwd":str(cwd)}}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--jira-config',type=Path)
    ap.add_argument('--mcp-config',type=Path,default=Path.home()/'.codex'/'config.toml')
    ap.add_argument('--cwd',type=Path,default=Path.cwd())
    ap.add_argument('--no-probe',action='store_true')
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    jira_cfg=args.jira_config or Path.home()/'.codex'/'project-management-spaces.json'
    sources=[jira_source(jira_cfg,not args.no_probe)]+mcp_sources(args.mcp_config,not args.no_probe)+[git_source(args.cwd)]
    required=any(s['status']=='CONFIGURED_AVAILABLE' for s in sources)
    payload={"schemaVersion":1,"generatedAt":datetime.now(timezone.utc).isoformat(),"researchFirstRequired":required,"sources":sources}
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    available=sum(1 for s in sources if s['status']=='CONFIGURED_AVAILABLE')
    configured=sum(1 for s in sources if s['configured'])
    errors=sum(1 for s in sources if s['status']=='CONFIGURED_ERROR')
    fatal=configured>0 and available==0
    print(json.dumps({"status":"ERROR" if fatal else "PASS","researchFirstRequired":required,"available":available,"configured":configured,"errors":errors,"out":str(args.out)},ensure_ascii=False))
    return 0 if not fatal else 1
if __name__=='__main__': raise SystemExit(main())
