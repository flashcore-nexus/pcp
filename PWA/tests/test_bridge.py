import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import io

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'dist/python'))
spec=importlib.util.spec_from_file_location('pcp_bridge',ROOT/'dist/python/bridge.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'tests/temporarios';parent.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        b.initialize(Path(self.temp.name)/'data');self.token=b.csrf
    def tearDown(self):self.temp.cleanup()
    def request(self,path,payload=None,raw=None,token=None):
        method='POST' if payload is not None or raw is not None else 'GET'
        return b.dispatch(method,path,{'x-pcp-csrf':self.token if token is None else token,'x-pcp-confirm':'true','x-pcp-filename':'Ensaio.pdf'},raw if raw is not None else json.dumps(payload).encode() if payload is not None else b'')
    def row(self):
        _,_,body=self.request('/api/state');value=json.loads(body);state=value['state']
        rid=state['nextId'];state['nextId']+=1
        state['rows'].append({'id':rid,'work':'Teste portátil','reference':'REF-'+str(rid),'owner':'Não atribuído','received':'2026-11-25','deadline':'2026-12-25','notes':'Sem dados reais','summary':state['summaryDefaults']['pending'],'labels':{m:state['defaults']['notStarted'] for m in state['materials']}})
        code,_,body=self.request('/api/state',{'revision':value['revision'],'state':state});self.assertEqual(code,200,body)
        return rid

    def test_portable_and_native_format_restore_preserve_attachment(self):
        rid=self.row();cells=json.loads(self.request('/api/attachments')[2])['cells'];cell=next(c for c in cells if c['work_id']==rid)
        self.assertEqual(self.request('/api/cells/'+cell['id']+'/attachments',raw=b'%PDF-1.4\nTeste\n%%EOF')[0],201)
        code,_,backup=self.request('/api/backup');self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            manifest=json.loads(z.read('manifesto.json'));self.assertEqual(manifest['backup_version'],1);self.assertEqual(manifest['schema'],5);self.assertIn('database_sha256',manifest)
        old_token=self.token
        code,_,result=self.request('/api/restore',raw=backup);self.assertEqual(code,200,result)
        self.assertNotEqual(old_token,b.csrf)
        state=json.loads(self.request('/api/state')[2]);self.assertEqual(len(state['state']['rows']),1)
        self.assertEqual(self.request('/api/state',{'revision':state['revision'],'state':state['state']},token=old_token)[0],403)
        # Formato completo anterior do PCP também é importável.
        native=b.store.backup_full();self.token=b.csrf
        code,_,result=self.request('/api/restore',raw=native.read_bytes());self.assertEqual(code,200,result)

    def test_invalid_backup_does_not_replace_current_data(self):
        self.row();previous=json.loads(self.request('/api/state')[2])['state']
        self.assertEqual(self.request('/api/restore',raw=b'nao-e-zip')[0],400)
        self.assertEqual(json.loads(self.request('/api/state')[2])['state'],previous)

    def test_wrong_database_hash_rejected_before_replacement(self):
        self.row();backup=self.request('/api/backup')[2];stream=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(backup)) as original,zipfile.ZipFile(stream,'w') as changed:
            for name in original.namelist():
                data=original.read(name)
                if name=='manifesto.json':
                    manifest=json.loads(data);manifest['database_sha256']='0'*64;data=json.dumps(manifest).encode()
                changed.writestr(name,data)
        previous=json.loads(self.request('/api/state')[2])['state']
        self.assertEqual(self.request('/api/restore',raw=stream.getvalue())[0],400)
        self.assertEqual(json.loads(self.request('/api/state')[2])['state'],previous)

    def test_backup_with_unrecognized_path_rejected(self):
        backup=self.request('/api/backup')[2];stream=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(backup)) as original,zipfile.ZipFile(stream,'w') as changed:
            for name in original.namelist():changed.writestr(name,original.read(name))
            changed.writestr('../fora-do-backup','invalido')
        self.assertEqual(self.request('/api/restore',raw=stream.getvalue())[0],400)


if __name__=='__main__':unittest.main()
