#!/usr/bin/env python3
"""Generate a neutral standalone Prototype and Manifest from a PRD's FR/AC contract."""
from __future__ import annotations
import argparse, hashlib, html, json, re, secrets
from datetime import datetime, timezone
from pathlib import Path
FR_RE=re.compile(r"\bFR-[0-9]{3}\b"); AC_RE=re.compile(r"\bAC-[0-9]{3}\b")
def main():
 ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--prd',type=Path,required=True); ap.add_argument('--prototype',type=Path,required=True); ap.add_argument('--manifest',type=Path,required=True); ap.add_argument('--workflow-id',required=True); ap.add_argument('--revision',required=True); args=ap.parse_args()
 text=args.prd.read_text(encoding='utf-8'); frs=[]; acs=[]
 section=None; permissions=[]; states=[]
 for line in text.splitlines():
  if line.startswith('#'):
   title=line.lstrip('#').strip().lower()
   section='permissions' if 'permission' in title or '权限' in title else ('states' if 'state' in title or '状态' in title else None)
   continue
  ids=FR_RE.findall(line); frs.extend(ids)
  acs.extend(AC_RE.findall(line))
  if section=='permissions' and line.strip().startswith('-'):
   permissions.append(line.strip().removeprefix('-').strip())
  if section=='states' and line.strip().startswith('-'):
   states.append(line.strip().removeprefix('-').strip())
 frs=list(dict.fromkeys(frs)); acs=list(dict.fromkeys(acs));
 if not frs: print(json.dumps({'status':'BLOCKED','reason':'PRD has no FR identifiers'})); return 1
 if not permissions: permissions=['UNSPECIFIED role may interact with the feature']
 if not states: states=['default: precondition defined by PRD']
 elements=[]
 for i,fr in enumerate(frs):
  ac=acs[i] if i<len(acs) else (acs[0] if acs else 'AC-001')
  ui='UI-'+fr; label=fr+' interaction'
  state_ids=[]
  for item in states:
   state_ids.append(item.split(':',1)[0].strip().split()[0])
  permission_ids=['P-'+ui+'-'+str(j+1) for j in range(len(permissions))]
  elements.append({'uiElementId':ui,'frIds':[fr],'acIds':[ac],'visibleLabel':label,'states':state_ids,'action':'bounded interaction','permissions':permissions,'permissionEdgeIds':permission_ids})
 buttons='\n'.join(f'<button data-ai-id="{html.escape(e["uiElementId"])}" data-ai-fr="{html.escape(e["frIds"][0])}" data-ai-ac="{html.escape(e["acIds"][0])}" data-ai-state="{html.escape(",".join(e["states"]))}" data-ai-permission-edge="{html.escape(",".join(e["permissionEdgeIds"]))}">{html.escape(e["visibleLabel"])}</button>' for e in elements)
 prd_hash=hashlib.sha256(args.prd.read_bytes()).hexdigest(); body=f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="source-prd" content="PRD_DELIVERY.md"><meta name="source-prd-sha256" content="{prd_hash}"><meta name="prototype-revision" content="{html.escape(args.revision)}"><title>Neutral Prototype</title></head><body><main><h1>Prototype</h1>{buttons}</main></body></html>\n'
 args.prototype.parent.mkdir(parents=True,exist_ok=True); args.prototype.write_text(body,encoding='utf-8'); proto_hash=hashlib.sha256(args.prototype.read_bytes()).hexdigest()
 manifest={'schemaVersion':1,'manifestId':'manifest-'+secrets.token_hex(4),'workflowId':args.workflow_id,'prototypeRevision':args.revision,'prototypePath':str(args.prototype.resolve()),'prototypeHash':proto_hash,'elements':elements,'createdAt':datetime.now(timezone.utc).isoformat()}
 args.manifest.parent.mkdir(parents=True,exist_ok=True); args.manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'status':'PASS','prototype':str(args.prototype),'manifest':str(args.manifest),'elements':len(elements)},ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
