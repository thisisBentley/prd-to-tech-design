import importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPTS='scripts' if ROOT.name=='ai-native-delivery' else 'tools'; TOOL=ROOT/SCRIPTS/'detect_research_capabilities.py'
class ResearchCapabilityTests(unittest.TestCase):
    def test_jira_token_file_alias_is_supported(self):
        spec=importlib.util.spec_from_file_location('research_capabilities',TOOL)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            credential_path=Path(td)/'jira-token'; credential_path.write_text('fixture-value\n',encoding='utf-8')
            self.assertEqual(module.jira_credential({'tokenFile':str(credential_path)}),'fixture-value')
    def test_jira_token_env_alias_is_supported(self):
        spec=importlib.util.spec_from_file_location('research_capabilities_env',TOOL)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        os.environ['TEST_AI_NATIVE_JIRA_TOKEN']='env-token'
        try: self.assertEqual(module.jira_credential({'tokenEnv':'TEST_AI_NATIVE_JIRA_TOKEN'}),'env-token')
        finally: os.environ.pop('TEST_AI_NATIVE_JIRA_TOKEN',None)
    def run_tool(self,*args,expect=0):
        p=subprocess.run([sys.executable,str(TOOL),*map(str,args)],text=True,capture_output=True)
        self.assertEqual(p.returncode,expect,p.stdout+p.stderr)
        return json.loads(p.stdout)
    def test_no_sources_is_not_configured_and_normal_flow(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); jira=root/'jira.json'; mcp=root/'config.toml'; out=root/'out.json'
            jira.write_text(json.dumps({'spaces':{}})); mcp.write_text('[mcp_servers.none]\nenabled = false\n')
            self.run_tool('--jira-config',jira,'--mcp-config',mcp,'--cwd',root,'--out',out)
            data=json.loads(out.read_text()); self.assertFalse(data['researchFirstRequired']); self.assertTrue(all(s['status']=='NOT_CONFIGURED' or s['configured'] is False for s in data['sources']))
    def test_configured_jira_without_credential_returns_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); jira=root/'jira.json'; mcp=root/'config.toml'; out=root/'out.json'
            jira.write_text(json.dumps({'spaces':{'j':{'provider':'jira','config':{'baseUrl':'https://invalid.example','auth':{'type':'bearer','tokenEnv':'MISSING_JIRA_TOKEN'}}}}})); mcp.write_text('')
            result=self.run_tool('--jira-config',jira,'--mcp-config',mcp,'--cwd',root,'--out',out,expect=1)
            self.assertEqual(result['status'],'ERROR'); data=json.loads(out.read_text()); self.assertTrue(any(s['source']=='JIRA' and s['status']=='CONFIGURED_ERROR' for s in data['sources']))
if __name__=='__main__': unittest.main()
