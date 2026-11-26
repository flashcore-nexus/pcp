"""SQLite, identidades estáveis e diretórios privados do PCP."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
import zipfile
import tempfile
import copy
from .validacao import validate, InvalidState


class Conflict(Exception):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


class Store:
    def __init__(self, directory, seed):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.files = self.directory / 'arquivos'
        self.backups = self.directory / 'backups'
        self.files.mkdir(exist_ok=True)
        self.backups.mkdir(exist_ok=True)
        self.path = self.directory / 'pcp.sqlite3'
        config = self.directory / 'armazenamento.json'
        if not config.exists():
            config.write_text(json.dumps({'max_file_bytes': 30 * 1024 * 1024, 'allowed_extensions': ['.pdf', '.png', '.jpg', '.jpeg', '.webp', '.doc', '.docx', '.xls', '.xlsx', '.dwg', '.dxf', '.zip'], 'uploads_enabled': True}, indent=2), encoding='utf-8')
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,state TEXT NOT NULL,updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sectors(id TEXT PRIMARY KEY,name TEXT NOT NULL,active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS works(id INTEGER PRIMARY KEY,uid TEXT NOT NULL UNIQUE,reference TEXT NOT NULL,title TEXT NOT NULL,metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS board_columns(id TEXT PRIMARY KEY,uid TEXT NOT NULL UNIQUE,sector_id TEXT NOT NULL REFERENCES sectors(id),position INTEGER NOT NULL,metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cells(id TEXT PRIMARY KEY,work_id INTEGER NOT NULL REFERENCES works(id),column_id TEXT NOT NULL REFERENCES board_columns(id),UNIQUE(work_id,column_id));
                CREATE TABLE IF NOT EXISTS cell_values(cell_id TEXT NOT NULL REFERENCES cells(id),kind TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(cell_id,kind));
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,cell_id TEXT NOT NULL REFERENCES cells(id),original_name TEXT NOT NULL,storage_key TEXT NOT NULL UNIQUE,size INTEGER NOT NULL,sha256 TEXT NOT NULL,created TEXT NOT NULL,deleted TEXT);
                CREATE INDEX IF NOT EXISTS documents_cell_live ON documents(cell_id,deleted,created,id);
                CREATE TABLE IF NOT EXISTS sector_settings(id TEXT PRIMARY KEY REFERENCES sectors(id),description TEXT NOT NULL,color TEXT NOT NULL,icon TEXT NOT NULL,position INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sector_boards(sector_id TEXT PRIMARY KEY REFERENCES sectors(id),state TEXT NOT NULL,updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS work_links(work_id INTEGER PRIMARY KEY REFERENCES works(id),project_id TEXT NOT NULL REFERENCES projects(id));
                CREATE INDEX IF NOT EXISTS work_links_project ON work_links(project_id);
                CREATE TABLE IF NOT EXISTS deletion_batches(id TEXT PRIMARY KEY,kind TEXT NOT NULL,target_id TEXT NOT NULL,created TEXT NOT NULL,restored TEXT);
                CREATE TABLE IF NOT EXISTS record_deletions(work_id INTEGER PRIMARY KEY REFERENCES works(id),batch_id TEXT NOT NULL REFERENCES deletion_batches(id));
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,created TEXT NOT NULL,entity TEXT NOT NULL,entity_id TEXT NOT NULL,action TEXT NOT NULL,before_hash TEXT,after_hash TEXT,before_data TEXT,after_data TEXT);
            ''')
            db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('namespace', str(uuid.uuid4())))
        if self.read() is None:
            self.save(seed, 0, action='initial_examples')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('sector_revision', '1'))
            db.execute('INSERT OR IGNORE INTO sector_settings VALUES (?,?,?,?,?)', (self.primary_sector(db), '', '#315acb', '▦', 0))
            from .obras import Works
            Works(self).sync_links(db)
            if db.execute('PRAGMA user_version').fetchone()[0] < 4:
                db.execute('PRAGMA user_version=4')
            if db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():
                from .fluxo import schema
                schema(db)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def primary_sector(self, db):
        namespace = uuid.UUID(db.execute('SELECT value FROM meta WHERE key=?', ('namespace',)).fetchone()[0])
        return str(uuid.uuid5(namespace, 'sector:compras'))

    def require_sector(self, db, sector_id=None, active=True):
        if sector_id is not None and not isinstance(sector_id, str):
            raise InvalidState('Identificador de setor inválido.')
        sector_id = self.primary_sector(db) if sector_id is None else str(uuid.UUID(sector_id))
        row = db.execute('SELECT active FROM sectors WHERE id=?', (sector_id,)).fetchone()
        if not row or (active and not row[0]):
            raise InvalidState('Setor não encontrado ou inativo. Escolha um setor ativo no menu.')
        return sector_id

    def board_row(self, db, sector_id=None):
        if sector_id is None or sector_id == self.primary_sector(db):
            return db.execute('SELECT revision,state,updated FROM snapshot WHERE id=1').fetchone()
        return db.execute('SELECT p.revision,b.state,b.updated FROM snapshot p JOIN sector_boards b ON b.sector_id=? WHERE p.id=1', (sector_id,)).fetchone()

    def read(self, sector_id=None):
        with self.connect() as db:
            row = self.board_row(db, sector_id)
        return None if row is None else {'revision': row[0], 'state': json.loads(row[1]), 'updated': row[2]}

    def write_board(self, db, sector_id, state, now):
        if sector_id == self.primary_sector(db):
            db.execute('UPDATE snapshot SET state=?,updated=? WHERE id=1', (canonical(state), now))
        else:
            db.execute('INSERT INTO sector_boards VALUES (?,?,?) ON CONFLICT(sector_id) DO UPDATE SET state=excluded.state,updated=excluded.updated', (sector_id, canonical(state), now))

    @staticmethod
    def initial_row(row, state):
        result = {k: row[k] for k in ('id', 'work', 'reference', 'received', 'deadline')}
        result.update(owner='Não atribuído', notes='', summary=None, labels={c['key']: state['defaults']['notStarted'] for c in state['viewColumns'] if c['type'] == 'status' and not (c['kind'] == 'fixed' and c['key'] == 'summary')})
        if state.get('workflowVersion') == 1:
            result['summary'] = state['summaryDefaults']['pending']
            if 'projectCode' in row: result['projectCode'] = row['projectCode']
        return result

    def sync_catalog(self, db, source_id, state, revision, now):
        # Identidade/nome/romaneio são centrais; os demais campos ficam no setor.
        catalog = {r['id']: r for r in state['rows']}
        consolidated = bool(db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone())
        others = [(self.primary_sector(db), db.execute('SELECT state FROM snapshot WHERE id=1').fetchone()[0])]
        others += db.execute('SELECT sector_id,state FROM sector_boards').fetchall()
        for sid, serialized in others:
            if sid == source_id:
                continue
            before = json.loads(serialized)
            after = json.loads(serialized)
            existing = {r['id']: r for r in after['rows']}
            for wid, row in catalog.items():
                if wid not in existing:
                    if not consolidated:
                        after['rows'].append(self.initial_row(row, after))
                else:
                    existing[wid].update(work=row['work'], reference=row['reference'])
            if consolidated:
                for row in after['rows']:
                    row['work'] = db.execute('SELECT p.title FROM projects p JOIN work_links l ON l.project_id=p.id WHERE l.work_id=?',(row['id'],)).fetchone()[0]
                    row['projectCode'] = db.execute('SELECT d.code FROM project_details d JOIN work_links l ON l.project_id=d.project_id WHERE l.work_id=?',(row['id'],)).fetchone()[0]
            after['nextId'] = state['nextId']
            if before != after:
                validate(after)
                self.entities(db, after, before, revision, now, sid, update_catalog=False)
                self.write_board(db, sid, after, now)

    def save(self, state, expected_revision, action='update', sector_id=None, project_links=None):
        original = canonical(state)
        state = copy.deepcopy(state)
        validate(state)
        if any(c.get('restricted') for c in state['viewColumns']):
            raise InvalidState('Dados restritos indisponíveis: autenticação e permissões ainda não foram implementadas.')
        if type(expected_revision) is not int or expected_revision < 0:
            raise InvalidState('Revisão inválida.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            primary = self.primary_sector(db)
            if sector_id is None:
                db.execute('INSERT OR IGNORE INTO sectors VALUES (?,?,1)', (primary, 'Compras'))
            sector_id = self.require_sector(db, sector_id)
            old = self.board_row(db, sector_id)
            revision = old[0] if old else 0
            if expected_revision != revision:
                raise Conflict('Outra aba salvou uma versão mais recente. Nada foi sobrescrito.')
            previous = json.loads(old[1]) if old else None
            if previous:
                roles={c['id']:c.get('role') for c in previous['viewColumns']}
                for column in state['viewColumns']:
                    if column.get('role') != roles.get(column['id']):
                        raise InvalidState('A função de identificação/compartilhamento da coluna deve ser preservada.')
                if not {r['id'] for r in previous['rows']} <= {r['id'] for r in state['rows']}:
                    raise InvalidState('Remover obras requer uma operação específica; nada foi gravado.')
                if not {c['id'] for c in previous['viewColumns']} <= {c['id'] for c in state['viewColumns']}:
                    raise InvalidState('As identidades das colunas devem ser preservadas.')
                if state['nextId'] < previous['nextId'] or state['columnSequence'] < previous['columnSequence']:
                    raise InvalidState('A sequência de identificadores não pode retroceder.')
            from .obras import Works
            works = Works(self)
            works.normalize_names(db, state, previous)
            from .consolidacao import normalize_codes
            if previous and previous.get('workflowVersion') == 1:
                if state.get('workflowVersion') != 1:
                    raise InvalidState('Reabra o quadro atualizado antes de salvar.')
                for row in state['rows']:
                    if row.get('summary') is None: row['summary'] = state['summaryDefaults']['pending']
            normalize_codes(db, state, previous)
            now = datetime.now(timezone.utc).isoformat()
            if state.get('workflowVersion') == 1:
                from .prazos import completion
                completion(state,previous,now)
            validate(state)
            if previous:
                if canonical(previous) == canonical(state):
                    return {'revision': revision, 'changed': False}
            revision += 1
            now = datetime.now(timezone.utc).isoformat()
            if state.get('workflowVersion') == 1:
                from .prazos import calculate
                calculate(self,db,state,sector_id,revision,now)
                validate(state)
            self.entities(db, state, previous, revision, now, sector_id)
            works.sync_links(db, project_links)
            normalize_codes(db, state, previous)
            db.execute('INSERT INTO snapshot VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,state=excluded.state,updated=excluded.updated', (revision, canonical(state) if sector_id == primary else db.execute('SELECT state FROM snapshot WHERE id=1').fetchone()[0], now))
            self.write_board(db, sector_id, state, now)
            self.sync_catalog(db, sector_id, state, revision, now)
            settings = lambda item: {k: v for k,v in item.items() if k not in {'rows', 'typeValues', 'viewColumns'}}
            db.execute('INSERT INTO audit(revision,created,entity,entity_id,action,before_hash,after_hash,before_data,after_data) VALUES (?,?,?,?,?,?,?,?,?)', (revision, now, 'board', sector_id, action, None if previous is None else digest(previous), digest(state), None if previous is None else canonical(settings(previous)), canonical(settings(state))))
        return {'revision': revision, 'changed': True, 'updated': now, **({'state': state} if canonical(state) != original else {})}

    def entities(self, db, state, previous, revision, now, sector_id, update_catalog=True):
        namespace = uuid.UUID(db.execute('SELECT value FROM meta WHERE key=?', ('namespace',)).fetchone()[0])
        identity = lambda name: str(uuid.uuid5(namespace, name))
        primary = self.primary_sector(db)
        storage_id = lambda cid: cid if sector_id == primary else sector_id + ':' + cid
        previous_works = {r['id']: r for r in previous['rows']} if previous else {}
        previous_columns = {c['id']: c for c in previous['viewColumns']} if previous else {}
        def audit(entity, eid, before, after):
            if before != after:
                db.execute('INSERT INTO audit(revision,created,entity,entity_id,action,before_hash,after_hash,before_data,after_data) VALUES (?,?,?,?,?,?,?,?,?)', (revision, now, entity, str(eid), 'create' if before is None else 'update', None if before is None else digest(before), digest(after), None if before is None else canonical(before), canonical(after)))
        for row in state['rows']:
            if update_catalog:
                old_work = db.execute('SELECT metadata FROM works WHERE id=?', (row['id'],)).fetchone()
                metadata = row if sector_id == primary or old_work is None else {**json.loads(old_work[0]), 'work': row['work'], 'reference': row['reference']}
                db.execute('INSERT INTO works VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET reference=excluded.reference,title=excluded.title,metadata=excluded.metadata', (row['id'], identity('work:' + str(row['id'])), row['reference'], row['work'], canonical(metadata)))
            audit('work', row['id'] if sector_id == primary else sector_id + ':' + str(row['id']), previous_works.get(row['id']), row)
        for position, column in enumerate(state['viewColumns']):
            owner = db.execute('SELECT sector_id FROM board_columns WHERE id=?', (storage_id(column['id']),)).fetchone()
            if owner is not None and owner[0] != sector_id:
                raise InvalidState('Identificador de coluna já pertence a outro setor. Nada foi sobrescrito.')
            db.execute('INSERT INTO board_columns VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET position=excluded.position,metadata=excluded.metadata', (storage_id(column['id']), identity('column:' + storage_id(column['id'])), sector_id, position, canonical(column)))
            before_column = previous_columns.get(column['id'])
            audit('column', storage_id(column['id']), None if before_column is None else {'position': next(i for i,c in enumerate(previous['viewColumns']) if c['id'] == column['id']), **before_column}, {'position': position, **column})
        def cell_value(cell_id, kind, value):
            old_value = db.execute('SELECT value FROM cell_values WHERE cell_id=? AND kind=?', (cell_id, kind)).fetchone()
            if old_value is None or old_value[0] != canonical(value):
                audit('cell', cell_id + ':' + kind, None if old_value is None else json.loads(old_value[0]), value)
            db.execute('INSERT INTO cell_values VALUES (?,?,?) ON CONFLICT(cell_id,kind) DO UPDATE SET value=excluded.value', (cell_id, kind, canonical(value)))
        # Identidade da célula independe do título, ordem ou tipo da coluna.
        for row in state['rows']:
            for column in state['viewColumns']:
                cell_id = identity('cell:' + str(row['id']) + ':' + storage_id(column['id']))
                db.execute('INSERT OR IGNORE INTO cells VALUES (?,?,?)', (cell_id, row['id'], storage_id(column['id'])))
                value = None
                if column['kind'] == 'fixed' and column['key'] in {'work', 'owner', 'deadline'}:
                    cell_value(cell_id, column['originalType'], row[column['key']])
                if column['kind'] == 'fixed' and column['key'] == 'summary':
                    value = row.get('summary')
                elif column['key'] in row['labels']:
                    value = row['labels'][column['key']]
                else:
                    continue
                cell_value(cell_id, 'status', value)
        for cid, by_row in state['typeValues']:
            for rid, by_type in by_row:
                cell_id = identity('cell:' + str(rid) + ':' + storage_id(cid))
                for kind, value in by_type:
                    cell_value(cell_id, kind, value)

    def backup(self):
        destination = self.backups / ('pcp-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.sqlite3')
        with self.connect() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
        return destination

    def daily_backup(self):
        if not list(self.backups.glob('pcp-completo-' + datetime.now().strftime('%Y%m%d') + '-*.zip')):
            return self.backup_full()

    def backup_full(self):
        destination = self.backups / ('pcp-completo-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.zip')
        temporary = destination.with_suffix('.pending')
        try:
            with tempfile.TemporaryDirectory(prefix='pcp-backup-', dir=self.backups) as directory:
                if not Path(directory).resolve().is_relative_to(self.backups.resolve()) or Path(directory).resolve() == self.backups.resolve():
                    raise ValueError('Diretório temporário de backup fora da área prevista.')
                copy = Path(directory) / 'pcp.sqlite3'
                with self.connect() as source, closing(sqlite3.connect(copy)) as target:
                    source.backup(target)
                with closing(sqlite3.connect(copy)) as db:
                    documents = db.execute('SELECT id,sha256 FROM documents').fetchall()
                with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                    archive.write(copy, 'pcp.sqlite3')
                    archive.write(self.directory / 'armazenamento.json', 'armazenamento.json')
                    for docid, checksum in documents:
                        path = self.private_file_path(docid)
                        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                            raise OSError('Arquivo ausente ou divergente no backup.')
                        archive.write(path, 'arquivos/' + path.parent.name + '/' + path.name)
                    archive.writestr('manifesto.json', canonical({'documents': dict(documents), 'created': datetime.now(timezone.utc).isoformat()}))
            temporary.replace(destination)
            return destination
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def private_file_path(self, file_id):
        # Somente UUID gerado no servidor é usado como caminho físico.
        parsed = uuid.UUID(file_id)
        path = self.files / parsed.hex[:2] / parsed.hex
        if not path.resolve().is_relative_to(self.files.resolve()):
            raise ValueError('Caminho inválido.')
        return path
