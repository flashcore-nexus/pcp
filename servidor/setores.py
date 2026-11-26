"""Cadastro de setores e criação de quadros com o componente já existente."""
from datetime import datetime, timezone
import json
import re
import uuid
from .armazenamento import Conflict, canonical
from .validacao import validate, text, key, InvalidState

ICONS = ['▦', '◈', '⚙', '📐', '🏭', '🚚', '💼', '📦']


class Sectors:
    def __init__(self, store):
        self.store = store

    def listing(self, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.listing(connection)
        primary = self.store.primary_sector(db)
        rows = db.execute('SELECT s.id,s.name,s.active,c.description,c.color,c.icon,c.position FROM sectors s JOIN sector_settings c ON c.id=s.id ORDER BY c.position,s.id').fetchall()
        items = []
        models=dict(db.execute('SELECT sector_id,model FROM sector_models')) if db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone() else {}
        for sid, name, active, description, color, icon, position in rows:
            documents = db.execute('SELECT count(*) FROM documents d JOIN cells c ON c.id=d.cell_id JOIN board_columns b ON b.id=c.column_id WHERE b.sector_id=? AND d.deleted IS NULL', (sid,)).fetchone()[0]
            board = self.store.board_row(db, sid)
            items.append({'id': sid, 'name': name, 'active': bool(active), 'description': description, 'color': color, 'icon': icon, 'position': position, 'is_primary': sid == primary, 'works': len(json.loads(board[1])['rows']) if board else 0, 'documents': documents})
            items[-1]['model']=models.get(sid)
        revision = int(db.execute("SELECT value FROM meta WHERE key='sector_revision'").fetchone()[0])
        return {'revision': revision, 'sectors': items, 'icons': ICONS}

    @staticmethod
    def normalized(name):
        return key(' '.join(name.split()))

    def attributes(self, payload):
        name = ' '.join(text(payload['name'], 60, empty=False).split())
        description = text(payload.get('description', ''), 300).strip()
        color, icon = payload.get('color') or '#315acb', payload.get('icon') or '▦'
        if not isinstance(color, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', color) is None or icon not in ICONS:
            raise InvalidState('Cor ou ícone do setor inválido.')
        return name, description, color, icon

    def initial_board(self, db):
        # Reutiliza o esquema, sem copiar etiquetas/valores específicos de Compras.
        primary = json.loads(self.store.board_row(db)[1])
        state = json.loads(canonical(primary))
        state.update(materials=['Etapa'], stages=['Não iniciado', 'Em andamento', 'Aguardando liberação', 'Concluído', 'Não se aplica'], customColors=[['Não iniciado', '#8894aa'], ['Em andamento', '#e39136'], ['Aguardando liberação', '#b99537'], ['Concluído', '#25876f'], ['Não se aplica', '#e9edf4']], excluded=['Não se aplica'], purchased=['Concluído'], typeValues=[], deletedColumns=[], filters={'search': '', 'material': '', 'stage': ''}, columnSequence=2)
        state['defaults'] = {'notStarted': 'Não iniciado', 'notApplicable': 'Não se aplica', 'approval': 'Aguardando liberação'}
        state['summaryStages'] = ['Em andamento', 'Concluída', 'Parado', 'Pendência', 'Sem itens previstos']
        state['summaryDefaults'] = {'pending': 'Em andamento', 'done': 'Concluída', 'empty': 'Sem itens previstos'}
        state['summaryDone'] = ['Concluída']
        state['summaryColors'] = [['Em andamento', '#e39136'], ['Concluída', '#3377cc'], ['Parado', '#cf6681'], ['Pendência', '#c84b97'], ['Sem itens previstos', '#e9edf4']]
        fixed = {'work': 'text', 'owner': 'people', 'deadline': 'date', 'summary': 'status', 'actions': 'action'}
        state['fixedHeaders'] = {'work': 'Obra / romaneio', 'owner': 'Responsável', 'deadline': 'Prazo', 'summary': 'Status do setor', 'actions': 'Dados'}
        state['viewColumns'] = [{'id': 'fixed-'+k, 'kind': 'fixed', 'key': k, 'type': v, 'originalType': v} for k, v in fixed.items() if k != 'actions']
        state['viewColumns'] += [{'id': 'material-1', 'kind': 'material', 'key': 'Etapa', 'type': 'status', 'originalType': 'status'}, {'id': 'fixed-actions', 'kind': 'fixed', 'key': 'actions', 'type': 'action', 'originalType': 'action'}]
        state['rows'] = [self.store.initial_row(row, state) for row in primary['rows']]
        if db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():
            state['rows']=[]
            state['workflowVersion']=1
            state['labelDescriptions']={s:'Etapa personalizada deste setor.' for s in state['stages']+state['summaryStages']}
        validate(state)
        return state

    def mutate(self, payload):
        action = payload['action']
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.listing(db)
            if type(payload.get('revision')) is not int or payload['revision'] != current['revision']:
                raise Conflict('Os setores mudaram em outra aba. Reabra a organização dos setores antes de tentar novamente.')
            before = current['sectors']
            now = datetime.now(timezone.utc).isoformat()
            sid = payload.get('id')
            if action in {'create', 'edit'}:
                name, description, color, icon = self.attributes(payload)
                if any(self.normalized(s['name']) == self.normalized(name) and (action == 'create' or s['id'] != sid) for s in before):
                    raise InvalidState('Já existe um setor com esse nome, inclusive entre os inativos.')
                if action == 'create':
                    if len(before) >= 100:
                        raise InvalidState('Limite local de 100 setores atingido.')
                    sid = str(uuid.uuid4())
                    db.execute('INSERT INTO sectors VALUES (?,?,1)', (sid, name))
                    db.execute('INSERT INTO sector_settings VALUES (?,?,?,?,?)', (sid, description, color, icon, len(before)))
                    state = self.initial_board(db)
                    self.store.entities(db, state, None, self.store.board_row(db)[0], now, sid, update_catalog=False)
                    self.store.write_board(db, sid, state, now)
                else:
                    self.store.require_sector(db, sid, active=False)
                    db.execute('UPDATE sectors SET name=? WHERE id=?', (name, sid))
                    db.execute('UPDATE sector_settings SET description=?,color=?,icon=? WHERE id=?', (description, color, icon, sid))
            elif action == 'active':
                sid = self.store.require_sector(db, sid, active=False)
                active = payload['active']
                if type(active) is not bool:
                    raise InvalidState('Estado do setor inválido.')
                if not active and payload.get('confirm') is not True:
                    raise InvalidState('Confirme a inativação. Os dados serão preservados.')
                if not active and not any(s['active'] and s['id'] != sid for s in before):
                    raise InvalidState('Mantenha pelo menos um setor ativo.')
                db.execute('UPDATE sectors SET active=? WHERE id=?', (int(active), sid))
            elif action == 'reorder':
                ids = payload['ids']
                if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) != len(before) or set(ids) != {s['id'] for s in before}:
                    raise InvalidState('A ordem precisa conter cada setor exatamente uma vez.')
                for position, item in enumerate(ids):
                    db.execute('UPDATE sector_settings SET position=? WHERE id=?', (position, item))
            else:
                raise InvalidState('Operação de setor não permitida.')
            db.execute("UPDATE meta SET value=? WHERE key='sector_revision'", (str(current['revision'] + 1),))
            after = self.listing(db)
            db.execute('INSERT INTO audit(revision,created,entity,entity_id,action,before_data,after_data) VALUES (?,?,?,?,?,?,?)', (self.store.board_row(db)[0], now, 'sector', sid or 'order', action, canonical(before), canonical(after['sectors'])))
        return {**after, 'changed_id': sid}
