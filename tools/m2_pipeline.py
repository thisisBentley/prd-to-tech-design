#!/usr/bin/env python3
"""Run the deterministic M2 generation, pair, runtime, U1/U2 and final gates."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path
def run(cmd,cwd):
 p=subprocess.run(cmd,cwd=cwd,text=True,capture_output=True); return p.returncode,p.stdout,p.stderr
def main():
 ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--workflow-id',required=True); ap.add_argument('--prd',type=Path,required=True); ap.add_argument('--out-dir',type=Path,required=True); ap.add_argument('--revision',default='r1'); ap.add_argument('--browser-runner',nargs='+'); ap.add_argument('--browser-timeout',type=float,default=30); ap.add_argument('--require-real-browser',action='store_true'); args=ap.parse_args(); out=args.out_dir.resolve(); out.mkdir(parents=True,exist_ok=True); scripts=Path(__file__).resolve().parent; py=sys.executable
 proto=out/'Prototype.html'; manifest=out/'prototype-manifest.json'; prev=out/'previous-manifest.json'; overview=out/'Overview.html'
 code,out_text,err=run([py,str(scripts/'generate_prototype_from_prd.py'),'--prd',str(args.prd),'--prototype',str(proto),'--manifest',str(manifest),'--workflow-id',args.workflow_id,'--revision',args.revision],out)
 steps=[{'step':'prototype-producer','returnCode':code,'stdout':out_text,'stderr':err}]
 if code: print(json.dumps({'status':'M2_BLOCKED','steps':steps})); return 1
 shutil.copyfile(manifest,prev)
 cmd=[py,str(scripts/'artifact_sync_loop.py'),'--workflow-id',args.workflow_id,'--prd',str(args.prd),'--prototype',str(proto),'--manifest',str(manifest),'--previous-manifest',str(prev),'--overview',str(overview),'--from-revision',args.revision,'--to-revision',args.revision,'--apply-reconcile','--generate-overview','--m2-complete','--out-dir',str(out),'--browser-timeout',str(args.browser_timeout)]
 if args.browser_runner: cmd.extend(['--browser-runner',*args.browser_runner])
 if args.require_real_browser: cmd.append('--require-real-browser')
 code,out_text,err=run(cmd,out); steps.append({'step':'m2-artifact-loop','returnCode':code,'stdout':out_text,'stderr':err})
 try: result=json.loads(out_text)
 except Exception: result={'status':'M2_BLOCKED','steps':steps}
 result['steps']=steps+result.get('steps',[]); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result.get('status')=='M2_FINAL_PASS' else 1
if __name__=='__main__': raise SystemExit(main())
