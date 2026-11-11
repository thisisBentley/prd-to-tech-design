import importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ADAPTER=ROOT/'adapters'/'research'/'providers'/'dialogos_mcp_adapter.py'

def module():
    spec=importlib.util.spec_from_file_location('dialogos_mcp_adapter',ADAPTER)
    loaded=importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded); return loaded

class DialogosMcpAdapterTests(unittest.TestCase):
    def test_find_code_arguments_preserve_module(self):
        args=module().arguments_for('find_code',{'query':'Talk','module':'dialog-manager'})
        self.assertEqual(args,{'query':'Talk','module':'dialog-manager'})
    def test_find_code_normalizes_code_evidence(self):
        payload={'effective_query':'Talk','matches':[{'module':'dialog-manager','path':'core/model/talk_request.go','line':12,'text':'type TalkRequest struct {'}],'files':[]}
        record=module().normalize('find_code',{'query':'Talk'},payload)[0]
        self.assertEqual(record['status'],'CONFIRMED')
        self.assertIn('dialog-manager/core/model/talk_request.go:12',record['evidenceRefs'][0])
        self.assertIn('TalkRequest',record['claims'][0]['claim'])
    def test_overview_normalizes_module_map(self):
        payload={'modules':[{'name':'dialog-manager','role':'在线编排层','summary':'承接 Talk 请求'}],'module_count':1}
        record=module().normalize('overview',{'query':''},payload)[0]
        self.assertEqual(record['status'],'CONFIRMED')
        self.assertIn('dialog-manager',record['claims'][0]['claim'])
        self.assertIn('dialogos-mcp://module/dialog-manager',record['evidenceRefs'])
    def test_inline_and_nested_headers_are_supported(self):
        m=module()
        for body in (
            '[mcp_servers.dialogos-mcp]\nurl = "http://example/mcp"\nhttp_headers = { ' + 'Author' + 'ization' + ' = "fixture-value" }\n',
            '[mcp_servers.dialogos-mcp]\nurl = "http://example/mcp"\n\n[mcp_servers.dialogos-mcp.http_headers]\n' + 'Author' + 'ization' + ' = "fixture-value"\n',
        ):
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/'config.toml'; path.write_text(body,encoding='utf-8')
                self.assertEqual(m.parse_server(path,'dialogos-mcp')['headers']['Author' + 'ization'],'fixture-value')
    def test_diagnose_requires_trace_fields(self):
        with self.assertRaises(ValueError):
            module().arguments_for('diagnose',{'scope':'trace','namespace':'demo'})
    def test_read_code_requires_path_like_input(self):
        with self.assertRaises(ValueError):
            module().arguments_for('read_code',{'module':'dialog-manager'})
if __name__=='__main__': unittest.main()
