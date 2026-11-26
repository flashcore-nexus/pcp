"""Obras com vários romaneios e lixeira recuperável do perfil pessoal local."""
from datetime import datetime, timezone
import copy
import json
import uuid
from .armazenamento import Conflict, canonical
from .validacao import InvalidState


class Works:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def identifier(value):
        if not isinstance(value, str):
            raise InvalidState('Identificador da obra ou exclusão inválido.')
        return str(uuid.UUID(value))

    def sync_links(self, db, requested=None):
        requested = requested or {}
        namespace = uuid.UUID(db.execute("SELECT value FROM meta WHERE key='namespace'").fetchone()[0])
        for rid, uid, title in db.execute('SELECT id,uid,title FROM works ORDER BY id').fetchall():
            existing = db.execute('SELECT project_id FROM work_links WHERE work_id=?', (rid,)).fetchone()
            if existing:
                if rid in requested and requested[rid] != existing[0]:
                    raise InvalidState('O vínculo de um romaneio existente não pode ser trocado nesta operação.')
                continue
            if rid in requested:
                pid = self.identifier(requested[rid])
                project = db.execute('SELECT title FROM projects WHERE id=?', (pid,)).fetchone()
                active = db.execute('SELECT count(*) FROM work_links l WHERE l.project_id=? AND NOT EXISTS (SELECT 1 FROM record_deletions d WHERE d.work_id=l.work_id)', (pid,)).fetchone()[0]
                if not project or not active or project[0] != title:
                    raise InvalidState('Escolha uma obra ativa e mantenha seu nome ao adicionar o romaneio.')
            else:
                pid = str(uuid.uuid5(namespace, 'project:' + uid))
                db.execute('INSERT INTO projects VALUES (?,?,?)', (pid, title, datetime.now(timezone.utc).isoformat()))
            db.execute('INSERT INTO work_links VALUES (?,?)', (rid, pid))
            if db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():
                db.execute('INSERT OR IGNORE INTO project_details(project_id,code) VALUES (?,?)', (pid, 'OBR-' + pid.replace('-','').upper()))

    def normalize_names(self, db, state, previous):
        if previous is None:
            return
        old = {r['id']: r for r in previous['rows']}
        links = dict(db.execute('SELECT work_id,project_id FROM work_links'))
        changes = {}
        for row in state['rows']:
            if row['id'] in old and row['work'] != old[row['id']]['work']:
                pid = links[row['id']]
                changes.setdefault(pid, set()).add(row['work'])
        if any(len(names) != 1 for names in changes.values()):
            raise InvalidState('Os romaneios da mesma obra devem compartilhar o mesmo nome.')
        for pid, names in changes.items():
            title = next(iter(names))
            db.execute('UPDATE projects SET title=? WHERE id=?', (title, pid))
            for row in state['rows']:
                if links.get(row['id']) == pid:
                    row['work'] = title

    def listing(self, db=None):
        if db is None:
            with self.store.connect() as connection:
                connection.execute('BEGIN')
                return self.listing(connection)
        records = {}
        deleted = []
        for rid, pid, reference, batch in db.execute('SELECT w.id,l.project_id,w.reference,d.batch_id FROM works w JOIN work_links l ON l.work_id=w.id LEFT JOIN record_deletions d ON d.work_id=w.id ORDER BY w.id'):
            records.setdefault(pid, []).append({'id': rid, 'reference': reference, 'deleted': batch is not None})
            if batch is not None:
                deleted.append(rid)
        projects = [{'id': pid, 'name': title, 'records': records.get(pid, [])} for pid, title in db.execute('SELECT id,title FROM projects ORDER BY created,id')]
        batches = []
        for bid, kind, target, created in db.execute('SELECT id,kind,target_id,created FROM deletion_batches WHERE restored IS NULL ORDER BY created DESC,id'):
            entries = db.execute('SELECT w.id,w.reference,p.title FROM record_deletions d JOIN works w ON w.id=d.work_id JOIN work_links l ON l.work_id=w.id JOIN projects p ON p.id=l.project_id WHERE d.batch_id=? ORDER BY w.id', (bid,)).fetchall()
            if entries:
                batches.append({'id': bid, 'kind': kind, 'created': created, 'records': [{'id': r[0], 'reference': r[1], 'work': r[2]} for r in entries]})
        return {'revision': self.store.board_row(db)[0], 'projects': projects, 'deleted_record_ids': deleted, 'batches': batches, 'profile': 'local', 'can_delete': True, 'can_restore': True}

    def create_record(self, payload, sector_id):
        pid = self.identifier(payload['project_id'])
        with self.store.connect() as db:
            sector_id = self.store.require_sector(db, sector_id)
            project = db.execute('SELECT title FROM projects WHERE id=?', (pid,)).fetchone()
            if db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():
                commercial=db.execute("SELECT sector_id FROM sector_models WHERE model='Comercial'").fetchone()
                if commercial and sector_id!=commercial[0]:
                    commercial_state=json.loads(self.store.board_row(db,commercial[0])[1])
                    member_ids={rid for (rid,) in db.execute('SELECT work_id FROM work_links WHERE project_id=?',(pid,))}
                    proposals=[r for r in commercial_state['rows'] if r['id'] in member_ids]
                    if proposals and not db.execute("SELECT 1 FROM flow_events WHERE project_id=? AND action='confirm_sale' LIMIT 1",(pid,)).fetchone():
                        raise InvalidState('Confirme a venda no Comercial antes de vincular esta proposta a outro setor.')
        if project is None:
            raise InvalidState('Obra não encontrada.')
        loaded = self.store.read(sector_id)
        state = copy.deepcopy(loaded['state'])
        values = payload['fields']
        if not isinstance(values, dict) or set(values) != {'work', 'reference', 'owner', 'received', 'deadline', 'notes'}:
            raise InvalidState('Informe todos os dados do romaneio.')
        rid = state['nextId']
        row = {**values, 'id': rid, 'summary': None, 'labels': {m: state['defaults']['notStarted'] for m in state['materials']}}
        for column in state['viewColumns']:
            if column['type'] == 'status' and not (column['kind'] == 'fixed' and column['key'] == 'summary'):
                row['labels'][column['key']] = state['defaults']['notStarted']
        if values['work'] != project[0]:
            raise InvalidState('O novo romaneio deve manter o nome da obra escolhida.')
        state['rows'].append(row)
        state['nextId'] += 1
        result = self.store.save(state, payload['revision'], sector_id=sector_id, project_links={rid: pid})
        return {**result, 'record_id': rid}

    def mutate(self, payload, sector_id=None):
        action = payload['action']
        if action == 'create_record':
            return self.create_record(payload, sector_id)
        if action not in {'delete_project', 'delete_record', 'restore'}:
            raise InvalidState('Operação de obra não permitida.')
        if payload.get('confirm') is not True:
            raise InvalidState('Confirme a operação antes de continuar.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store.require_sector(db, sector_id)
            revision = self.store.board_row(db)[0]
            if type(payload.get('revision')) is not int or revision != payload['revision']:
                raise Conflict('O cadastro mudou em outra aba. Atualize e confirme novamente; nada foi excluído ou restaurado.')
            now = datetime.now(timezone.utc).isoformat()
            if action == 'restore':
                bid = self.identifier(payload['batch_id'])
                rows = db.execute('SELECT work_id FROM record_deletions WHERE batch_id=?', (bid,)).fetchall()
                if not rows:
                    raise InvalidState('Esta exclusão não está mais na lixeira.')
                db.execute('DELETE FROM record_deletions WHERE batch_id=?', (bid,))
                db.execute('UPDATE deletion_batches SET restored=? WHERE id=?', (now, bid))
                target = bid
            else:
                if action == 'delete_project':
                    target = self.identifier(payload['project_id'])
                    candidates = db.execute('SELECT work_id FROM work_links WHERE project_id=?', (target,)).fetchall()
                else:
                    target = payload['record_id']
                    if type(target) is not int:
                        raise InvalidState('Identificador do romaneio inválido.')
                    candidates = db.execute('SELECT id FROM works WHERE id=?', (target,)).fetchall()
                rows = [r for r in candidates if not db.execute('SELECT 1 FROM record_deletions WHERE work_id=?', (r[0],)).fetchone()]
                if not rows:
                    raise InvalidState('Nenhum romaneio ativo encontrado para esta operação.')
                bid = str(uuid.uuid4())
                db.execute('INSERT INTO deletion_batches VALUES (?,?,?,?,NULL)', (bid, action, str(target), now))
                db.executemany('INSERT INTO record_deletions VALUES (?,?)', [(r[0], bid) for r in rows])
            # Os registros, quadros, células e bytes permanecem nos mesmos locais.
            db.execute('UPDATE snapshot SET revision=?,updated=? WHERE id=1', (revision + 1, now))
            db.execute('INSERT INTO audit(revision,created,entity,entity_id,action,after_data) VALUES (?,?,?,?,?,?)', (revision + 1, now, 'work_lifecycle', str(target), action, canonical({'records': [r[0] for r in rows], 'profile': 'local', 'batch_id': bid})))
        return {'revision': revision + 1, 'affected_records': len(rows)}
