"""Adaptador de transporte local. Reutiliza os módulos originais, sem servidor HTTP."""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from urllib.parse import urlsplit, parse_qs, unquote, quote
from servidor.armazenamento import Store, Conflict
from servidor.validacao import validate, InvalidState, MAX_BYTES
from servidor.consolidacao import migrate
from servidor.anexos import Documents
from servidor.setores import Sectors
from servidor.obras import Works
from servidor.fluxo import Flow

DATA=Path('/pcp/data')
SEED=json.loads((Path(__file__).parent/'servidor/seed.json').read_text())
store=None
csrf=''


def initialize(directory=None):
    global store,csrf,DATA
    if directory is not None:DATA=Path(directory)
    store=Store(DATA,SEED)
    if not any(store.directory.glob('*.sqlite3')):raise ValueError('Armazenamento indisponível.')
    with store.connect() as db:
        consolidated=db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone()
    if not consolidated:migrate(store)
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('pwa_csrf',uuid.uuid4().hex))
        csrf=db.execute("SELECT value FROM meta WHERE key='pwa_csrf'").fetchone()[0]
    return csrf


def validate_backup(path):
    """Não extrai caminhos fornecidos pelo ZIP e nunca modifica o armazenamento ativo."""
    folder=Path(tempfile.mkdtemp(prefix='pcp-restore-'))
    try:
        with zipfile.ZipFile(path) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)) or len(names)>50000 or sum(i.file_size for i in archive.infolist())>512*1024*1024:
                raise InvalidState('Backup muito grande, duplicado ou incompatível (limite descompactado: 512 MB).')
            required={'pcp.sqlite3','armazenamento.json','manifesto.json'}
            if not required<=set(names):raise InvalidState('Este arquivo não é um backup completo do PCP.')
            manifest=json.loads(archive.read('manifesto.json'))
            if manifest.get('backup_version',1)!=1:raise InvalidState('Versão de backup não suportada.')
            (folder/'pcp.sqlite3').write_bytes(archive.read('pcp.sqlite3'))
            if manifest.get('database_sha256') and hashlib.sha256((folder/'pcp.sqlite3').read_bytes()).hexdigest()!=manifest['database_sha256']:
                raise InvalidState('Hash do banco divergente no backup.')
            (folder/'armazenamento.json').write_bytes(archive.read('armazenamento.json'))
            with closing(sqlite3.connect(folder/'pcp.sqlite3')) as db:
                if db.execute('PRAGMA user_version').fetchone()[0]!=5:raise InvalidState('O backup deve usar o esquema PCP 5. Preserve o original para conversão assistida.')
                if db.execute('PRAGMA quick_check').fetchone()!=('ok',) or db.execute('PRAGMA foreign_key_check').fetchall():raise InvalidState('Banco do backup inconsistente.')
                if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():raise InvalidState('Estruturas não autorizadas no backup.')
                with store.connect() as current:
                    tables={r[0] for r in current.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    incoming={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                    if tables!=incoming:raise InvalidState('Estrutura do backup incompatível com esta versão.')
                    for table in tables:
                        # Nomes vêm da lista de tabelas do próprio aplicativo, não do arquivo externo.
                        if list(current.execute('PRAGMA table_info('+table+')'))!=list(db.execute('PRAGMA table_info('+table+')')):
                            raise InvalidState('Estrutura de tabela incompatível.')
                uuid.UUID(db.execute("SELECT value FROM meta WHERE key='namespace'").fetchone()[0])
                for serialized, in db.execute('SELECT state FROM snapshot UNION ALL SELECT state FROM sector_boards'):validate(json.loads(serialized))
                documents=db.execute('SELECT id,storage_key,sha256,size FROM documents').fetchall()
                if manifest['documents']!={did:sha for did,_,sha,_ in documents}:raise InvalidState('Manifesto de documentos divergente.')
                allowed=set(required)
                for did,key,sha,size in documents:
                    identifier=uuid.UUID(did).hex
                    if key!=did:raise InvalidState('Identidade de arquivo inválida.')
                    member='arquivos/'+identifier[:2]+'/'+identifier;allowed.add(member)
                    content=archive.read(member)
                    if len(content)!=size or hashlib.sha256(content).hexdigest()!=sha:raise InvalidState('Arquivo ausente ou corrompido no backup.')
                    destination=folder/member;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(content)
                if set(names)!=allowed:raise InvalidState('O backup contém arquivos não reconhecidos.')
        candidate=Store(folder,SEED)
        Documents(candidate).config();Works(candidate).listing();Sectors(candidate).listing();Flow(candidate).overview()
        return folder,len(documents)
    except Exception:
        shutil.rmtree(folder)
        raise


def restore(path,confirm=False):
    global csrf
    if confirm is not True:raise InvalidState('Confirme antes de substituir os dados deste dispositivo.')
    folder,count=validate_backup(path)
    try:
        recovery=store.backup_full()
        # A cópia anterior é mantida. Nenhum anexo antigo é apagado por esta operação.
        with store.connect() as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        with closing(sqlite3.connect(folder/'pcp.sqlite3')) as source,closing(sqlite3.connect(store.path)) as target:source.backup(target)
        shutil.copyfile(folder/'armazenamento.json',store.directory/'armazenamento.json')
        for source in (folder/'arquivos').rglob('*') if (folder/'arquivos').exists() else []:
            if source.is_file():
                target=store.files/source.parent.name/source.name;target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target)
        initialize()
        # Abas anteriores à restauração não podem gravar por coincidência de revisão.
        csrf=uuid.uuid4().hex
        with store.connect() as db:db.execute("UPDATE meta SET value=? WHERE key='pwa_csrf'",(csrf,))
        return {'restored':True,'documents':count,'recovery':recovery.name}
    finally:shutil.rmtree(folder)


def dispatch(method,path,headers,body,scope='/'):
    """Retorna status, cabeçalhos e bytes; a confirmação IndexedDB ocorre no worker."""
    try:
        url=urlsplit(path);query=parse_qs(url.query,keep_blank_values=True);selected=query.get('sector')
        if selected and (len(selected)!=1 or not selected[0]):raise InvalidState('Setor inválido.')
        sector=selected[0] if selected else None
        route=url.path;docs=Documents(store);works=Works(store);flow=Flow(store)
        if method not in {'GET','POST'}:return reply(405,{'error':'Método não permitido.'})
        if method=='POST' and headers.get('x-pcp-csrf')!=csrf:return reply(403,{'error':'Reabra o aplicativo para renovar a sessão local.'})
        attachment=re.fullmatch(r'/api/cells/([\w-]+)/attachments(?:/([\w-]+)/(download|preview|rename|delete))?',route)
        if attachment:
            cid,did,action=attachment.groups()
            if sector:
                with store.connect() as db:
                    sid=store.require_sector(db,sector)
                    owner=db.execute('SELECT b.sector_id FROM cells c JOIN board_columns b ON b.id=c.column_id WHERE c.id=?',(cid,)).fetchone()
                    if not owner or owner[0]!=sid:raise LookupError('Arquivo de outro setor.')
            if method=='GET' and action in {'download','preview'}:
                item,data,mime=docs.content(cid,did,action=='preview')
                return binary(data,mime,('inline' if action=='preview' else 'attachment')+"; filename*=UTF-8''"+quote(item['name'],safe=''))
            if method=='POST':
                if did is None:return reply(201,docs.upload(cid,unquote(headers.get('x-pcp-filename','')),body))
                if action in {'rename','delete'}:return reply(200,docs.change(cid,did,action,json.loads(body)))
        shared=re.fullmatch(r'/api/flow/files/([\w-]+)/([\w-]+)',route)
        if method=='GET' and shared:
            name,data,mime=flow.shared_content(*shared.groups(),sector)
            return binary(data,mime,"attachment; filename*=UTF-8''"+quote(name,safe=''))
        if route=='/api/backup' and method=='GET':
            backup=store.backup_full()
            portable=backup.with_suffix('.portable')
            try:
                with zipfile.ZipFile(backup) as source,zipfile.ZipFile(portable,'w',zipfile.ZIP_DEFLATED) as target:
                    manifest=json.loads(source.read('manifesto.json'))
                    manifest.update(format='flashcore-pcp',backup_version=1,schema=5,database_sha256=hashlib.sha256(source.read('pcp.sqlite3')).hexdigest())
                    for name in source.namelist():
                        if name!='manifesto.json':
                            with source.open(name) as incoming,target.open(name,'w') as outgoing:shutil.copyfileobj(incoming,outgoing)
                    target.writestr('manifesto.json',json.dumps(manifest))
                data=portable.read_bytes()
            finally:portable.unlink(missing_ok=True)
            # Exportar não acumula ZIPs na base; as cópias de recuperação de restauração são mantidas.
            backup.unlink()
            return binary(data,'application/zip','attachment; filename="PCP-backup-completo.zip"')
        if route=='/api/recovery' and method=='GET':
            name=query.get('name',[''])[0]
            if not re.fullmatch(r'pcp-completo-[\w-]+\.zip',name):raise InvalidState('Cópia de recuperação inválida.')
            return binary((store.backups/name).read_bytes(),'application/zip','attachment; filename="PCP-antes-da-restauracao.zip"')
        if route=='/api/restore' and method=='POST':
            staged=Path(tempfile.gettempdir())/('pcp-incoming-'+uuid.uuid4().hex+'.zip')
            try:
                if len(body)>512*1024*1024:raise InvalidState('Backup acima do limite de 512 MB.')
                staged.write_bytes(body)
                return reply(200,restore(staged,headers.get('x-pcp-confirm')=='true'))
            finally:staged.unlink(missing_ok=True)
        if method=='GET':
            if route=='/api/state':
                with store.connect() as db:
                    db.execute('BEGIN');sid=store.require_sector(db,sector);row=store.board_row(db,sid)
                    return reply(200,{'revision':row[0],'state':json.loads(row[1]),'updated':row[2],'csrf':csrf,'works':works.listing(db)})
            result={'/api/sectors':lambda:Sectors(store).listing(),'/api/works':works.listing,'/api/attachments':lambda:docs.listing(sector),'/api/flow':lambda:flow.listing(sector),'/api/overview':flow.overview,'/api/health':lambda:{'application':'PCP','api':1,'storage':'indexeddb-sqlite','uploads_enabled':docs.config()['uploads_enabled']}}
            if route in result:
                value=result[route]()
                if route=='/api/flow':
                    for transfer in value['transfers']:
                        for file in transfer['files']:file['url']=scope.rstrip('/')+file['url']
                return reply(200,value)
        if method=='POST':
            if len(body)>MAX_BYTES:raise InvalidState('Dados acima do limite local.')
            payload=json.loads(body)
            if route=='/api/state':return reply(200,store.save(payload['state'],payload['revision'],sector_id=sector))
            if route=='/api/sectors':return reply(200,Sectors(store).mutate(payload))
            if route=='/api/works':return reply(200,works.mutate(payload,sector))
            if route=='/api/flow':
                value=flow.mutate(payload,sector)
                for transfer in value['transfers']:
                    for file in transfer['files']:file['url']=scope.rstrip('/')+file['url']
                return reply(200,value)
        return reply(404,{'error':'Recurso local não disponível.'})
    except Conflict as error:return reply(409,{'error':str(error)})
    except LookupError as error:return reply(404,{'error':str(error)})
    except (ValueError,TypeError,KeyError,zipfile.BadZipFile,sqlite3.DatabaseError) as error:return reply(400,{'error':str(error)[:300]})
    except Exception as error:return reply(500,{'error':'Operação local não confirmada: '+str(error)[:180]})


def reply(status,value):return status,{'Content-Type':'application/json; charset=utf-8'},json.dumps(value,ensure_ascii=False).encode()
def binary(body,mime,disposition):return 200,{'Content-Type':mime,'Content-Disposition':disposition,'X-Content-Type-Options':'nosniff'},body
