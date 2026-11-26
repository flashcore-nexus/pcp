"""Encaminhamento explícito: acompanhamento no destino, documentos por referência.

Perfil pessoal local. Não recebe nem disponibiliza dados financeiros/restritos.
"""
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from .armazenamento import canonical, Conflict
from .validacao import InvalidState, validate, text
from .anexos import MIMES, PREVIEW


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),source TEXT NOT NULL REFERENCES sectors(id),destination TEXT NOT NULL REFERENCES sectors(id),record_id INTEGER NOT NULL REFERENCES works(id),notes TEXT NOT NULL,created TEXT NOT NULL,received TEXT,version INTEGER NOT NULL,UNIQUE(project_id,source,destination))')
    db.execute('CREATE TABLE IF NOT EXISTS transfer_files(transfer_id TEXT NOT NULL REFERENCES transfers(id),document_id TEXT NOT NULL REFERENCES documents(id),PRIMARY KEY(transfer_id,document_id))')
    db.execute('CREATE TABLE IF NOT EXISTS flow_events(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),sector_id TEXT NOT NULL REFERENCES sectors(id),created TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL)')


def deadline_info(row, state, today=None):
    today=today or date.today()
    done=row.get('summary') in state['summaryDone']
    remaining=(date.fromisoformat(row['deadline'])-today).days
    thresholds=row.get('deadlineThresholds',[7,3])
    level='concluída' if done else 'atrasado' if remaining<0 else 'urgente' if remaining<=thresholds[1] else 'atenção' if remaining<=thresholds[0] else 'normal'
    return {'date':row['deadline'],'days':remaining,'level':level,'closed':done}


class Flow:
    def __init__(self,store):self.store=store

    def available(self,db):
        if not db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():
            raise InvalidState('Conclua a preparação v1 antes de utilizar o fluxo.')

    def active_records(self,db,pid):
        return {rid for (rid,) in db.execute('SELECT work_id FROM work_links WHERE project_id=? AND NOT EXISTS (SELECT 1 FROM record_deletions d WHERE d.work_id=work_links.work_id)',(pid,))}

    def listing(self,sector=None):
        with self.store.connect() as db:
            db.execute('BEGIN');self.available(db)
            sector=self.store.require_sector(db,sector)
            transfers=[]
            for tid,pid,source,destination,rid,notes,created,received,version in db.execute('SELECT * FROM transfers WHERE source=? OR destination=? ORDER BY created DESC',(sector,sector)):
                if rid not in self.active_records(db,pid):continue
                files=[]
                for did,name,size in db.execute('SELECT d.id,d.original_name,d.size FROM documents d JOIN transfer_files f ON f.document_id=d.id WHERE f.transfer_id=?',(tid,)):
                    files.append({'id':did,'name':name,'size':size,'url':'/api/flow/files/'+tid+'/'+did})
                transfers.append({'id':tid,'project_id':pid,'source':source,'destination':destination,'record_id':rid,'notes':notes,'created':created,'received':received,'version':version,'files':files,'documentation_pending':not files})
            events=[{'created':created,'actor':actor,'action':action,'project_id':pid,'payload':json.loads(payload)} for created,actor,action,pid,payload in db.execute('SELECT created,actor,action,project_id,payload FROM flow_events WHERE sector_id=? ORDER BY created DESC,id DESC LIMIT 200',(sector,))]
            return {'revision':self.store.board_row(db)[0],'transfers':transfers,'events':events,'profile':'Operador local pessoal','restricted_available':False}

    def mutate(self,payload,sector=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self.available(db)
            sector=self.store.require_sector(db,sector)
            revision=self.store.board_row(db)[0]
            if type(payload.get('revision')) is not int or payload['revision']!=revision:raise Conflict('O quadro mudou. Atualize antes de confirmar o encaminhamento.')
            if payload.get('confirm') is not True:raise InvalidState('Confirme a operação.')
            now=datetime.now(timezone.utc).isoformat();action=payload.get('action')
            if action in {'archive_sector','restore_sector'}:
                state=json.loads(self.store.board_row(db,sector)[1]);previous=json.loads(canonical(state))
                row=next((r for r in state['rows'] if r['id']==payload.get('record_id')),None)
                if not row:raise InvalidState('Registro não disponível neste setor.')
                row['archived']=action=='archive_sector'
                self.store.entities(db,state,previous,revision+1,now,sector,update_catalog=False)
                self.store.write_board(db,sector,state,now)
                pid=db.execute('SELECT project_id FROM work_links WHERE work_id=?',(row['id'],)).fetchone()[0]
                self.event(db,pid,sector,now,action,{'record_id':row['id']})
            elif action in {'receive','request_correction'}:
                transfer=db.execute('SELECT id,project_id,source,destination,record_id FROM transfers WHERE id=?',(payload.get('transfer_id'),)).fetchone()
                if not transfer or transfer[3]!=sector or transfer[4] not in self.active_records(db,transfer[1]):raise InvalidState('Recebimento não disponível neste setor.')
                if action=='receive':db.execute('UPDATE transfers SET received=? WHERE id=?',(now,transfer[0]))
                message=text(payload.get('message',''),1000)
                if action=='request_correction' and not message.strip():raise InvalidState('Descreva a informação ou correção necessária.')
                for sid in {sector,transfer[2]}:self.event(db,transfer[1],sid,now,action,{'transfer_id':transfer[0],'message':message})
            elif action in {'forward','confirm_sale'}:
                source=json.loads(self.store.board_row(db,sector)[1]);rid=payload.get('record_id')
                if type(rid) is not int:raise InvalidState('Registro inválido.')
                row=next((r for r in source['rows'] if r['id']==rid),None)
                link=db.execute('SELECT project_id FROM work_links WHERE work_id=?',(rid,)).fetchone()
                if not row or row.get('archived') or not link or rid not in self.active_records(db,link[0]):raise InvalidState('Abra uma obra ativa do setor para encaminhar.')
                pid=link[0];destinations=payload.get('destinations')
                if not isinstance(destinations,list) or not 1<=len(destinations)<=20:raise InvalidState('Escolha os setores de destino.')
                ids=[d.get('sector_id') for d in destinations]
                if len(set(ids))!=len(ids) or sector in ids:raise InvalidState('Escolha destinos diferentes da origem, sem repetir.')
                model=db.execute('SELECT model FROM sector_models WHERE sector_id=?',(sector,)).fetchone()
                name=model[0] if model else ''
                if action=='confirm_sale':
                    from .validacao import key
                    if key(name)!='comercial':raise InvalidState('Confirme a venda pelo Comercial.')
                    measurement=db.execute("SELECT s.id FROM sectors s JOIN sector_models m ON m.sector_id=s.id WHERE m.model='Medição' AND s.active=1").fetchone()
                    if not measurement or ids!=[measurement[0]]:raise InvalidState('Confirmar venda encaminha exclusivamente à Medição.')
                elif name=='Comercial':raise InvalidState('Propostas só seguem para os setores após Confirmar venda.')
                for destination in destinations:
                    sid=self.store.require_sector(db,destination['sector_id'])
                    documents=destination.get('documents',[]);notes=text(destination.get('notes',''),1000)
                    if not isinstance(documents,list) or len(documents)>100 or len(set(documents))!=len(documents):raise InvalidState('Seleção de documentos inválida.')
                    for did in documents:
                        document=db.execute('SELECT d.id,b.metadata,c.work_id FROM documents d JOIN cells c ON c.id=d.cell_id JOIN board_columns b ON b.id=c.column_id WHERE d.id=? AND d.deleted IS NULL AND b.sector_id=?',(did,sector)).fetchone()
                        if not document or document[2] not in self.active_records(db,pid):raise InvalidState('O arquivo não pertence a esta obra no setor de origem.')
                        column=json.loads(document[1])
                        if column.get('restricted') or (name=='Comercial' and column.get('role')!='technical_documents'):
                            raise InvalidState('Documentos restritos não podem ser encaminhados. Utilize Documentos para Medição.')
                    target=json.loads(self.store.board_row(db,sid)[1]);previous=json.loads(canonical(target))
                    members=self.active_records(db,pid)
                    found=next((r for r in target['rows'] if r['id'] in members),None)
                    if found:target_id=found['id']
                    else:
                        # Nunca substitui status, notas, datas ou anexos já existentes no destino.
                        new=self.store.initial_row(row,target)
                        new['received']=date.today().isoformat();new['deadline']=max(new['received'],new['deadline'])
                        target['rows'].append(new);target_id=rid
                        validate(target);self.store.entities(db,target,previous,revision+1,now,sid,update_catalog=False)
                        self.store.write_board(db,sid,target,now)
                    prior=db.execute('SELECT id,version FROM transfers WHERE project_id=? AND source=? AND destination=?',(pid,sector,sid)).fetchone()
                    tid=prior[0] if prior else str(uuid.uuid4());version=prior[1]+1 if prior else 1
                    if prior:db.execute('UPDATE transfers SET notes=?,created=?,received=NULL,version=? WHERE id=?',(notes,now,version,tid))
                    else:db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,?,?,NULL,?)',(tid,pid,sector,sid,target_id,notes,now,version))
                    # Revisões acumulam referências sem copiar nem eliminar versões anteriores.
                    for did in documents:db.execute('INSERT OR IGNORE INTO transfer_files VALUES (?,?)',(tid,did))
                    detail={'transfer_id':tid,'source':sector,'destination':sid,'documents':documents,'notes':notes,'version':version,'documentation_pending':not documents}
                    for event_sector in [sector,sid]:self.event(db,pid,event_sector,now,action,detail)
                if action=='confirm_sale' or payload.get('complete') is True:
                    if row.get('summary') not in source['summaryDone']:row['completedAt']=now
                    row['summary']=source['summaryDefaults']['done'];validate(source)
                    before=json.loads(self.store.board_row(db,sector)[1]);self.store.entities(db,source,before,revision+1,now,sector,update_catalog=False);self.store.write_board(db,sector,source,now)
            else:raise InvalidState('Operação de fluxo inválida.')
            db.execute('UPDATE snapshot SET revision=?,updated=? WHERE id=1',(revision+1,now))
        return self.listing(sector)

    @staticmethod
    def event(db,pid,sector,now,action,detail):
        db.execute('INSERT INTO flow_events VALUES (?,?,?,?,?,?,?)',(str(uuid.uuid4()),pid,sector,now,'Operador local pessoal',action,canonical(detail)))

    def shared_content(self,tid,did,sector,preview=False):
        with self.store.connect() as db:
            self.available(db);sector=self.store.require_sector(db,sector)
            transfer=db.execute('SELECT project_id,destination,record_id FROM transfers WHERE id=?',(tid,)).fetchone()
            if not transfer or transfer[1]!=sector or transfer[2] not in self.active_records(db,transfer[0]):raise LookupError('Documento não compartilhado com este setor.')
            row=db.execute('SELECT d.original_name,d.size,d.sha256 FROM documents d JOIN transfer_files f ON f.document_id=d.id WHERE f.transfer_id=? AND d.id=?',(tid,did)).fetchone()
            if not row:raise LookupError('Documento não compartilhado.')
            name,size,sha=row
        extension=Path(name).suffix.lower()
        if preview and extension not in PREVIEW:raise InvalidState('Formato disponível apenas para baixar.')
        content=self.store.private_file_path(did).read_bytes()
        if len(content)!=size or hashlib.sha256(content).hexdigest()!=sha:raise OSError('Integridade do arquivo não confirmada.')
        return name,content,MIMES[extension]

    def overview(self):
        with self.store.connect() as db:
            db.execute('BEGIN');self.available(db)
            sectors=db.execute('SELECT s.id,s.name FROM sectors s JOIN sector_settings t ON t.id=s.id WHERE s.active=1 ORDER BY t.position,s.id').fetchall()
            models=dict(db.execute('SELECT sector_id,model FROM sector_models'))
            projects={p:{'id':p,'name':n,'code':c,'sectors':[]} for p,n,c in db.execute('SELECT p.id,p.title,d.code FROM projects p JOIN project_details d ON d.project_id=p.id')}
            links=dict(db.execute('SELECT work_id,project_id FROM work_links'));deleted={rid for (rid,) in db.execute('SELECT work_id FROM record_deletions')}
            alerts=[];counts={}
            for sid,name in sectors:
                state=json.loads(self.store.board_row(db,sid)[1]);seen=set()
                for row in state['rows']:
                    if row['id'] in deleted or row.get('archived'):continue
                    pid=links[row['id']];seen.add(pid)
                    deadline=deadline_info(row,state)
                    dates={'received':row['received'],'deadline':row['deadline']}
                    for column in state['viewColumns']:
                        if column['type']=='date' and column['kind']!='fixed' and not column.get('deleted'):
                            value=dict(dict(dict(state['typeValues']).get(column['id'],[])).get(row['id'],[])).get('date','')
                            if value:dates[column['id']]=value
                    projects[pid]['sectors'].append({'id':sid,'name':name,'record_id':row['id'],'status':row.get('summary') or state['summaryDefaults']['pending'],'deadline':deadline,'dates':dates,'completed_at':row.get('completedAt'),'notes':row.get('notes','')})
                    if deadline['level'] in {'atrasado','urgente','atenção'}:alerts.append({'id':sid+':'+str(row['id'])+':deadline','project_id':pid,'work':row['work'],'sector':name,'message':('Atrasado há '+str(-deadline['days'])+' dia(s)' if deadline['days']<0 else 'Prazo em '+str(deadline['days'])+' dia(s)'),'level':deadline['level']})
                counts[sid]=len(seen)
            items=[p for p in projects.values() if p['sectors']]
            def proposal(p):return all(models.get(s['id'])=='Comercial' for s in p['sectors']) and not db.execute("SELECT 1 FROM flow_events WHERE project_id=? AND action='confirm_sale' LIMIT 1",(p['id'],)).fetchone()
            def complete(p):return any(models.get(s['id'])=='Instalação' for s in p['sectors']) and all(s['deadline']['closed'] for s in p['sectors'])
            active=[p for p in items if not proposal(p) and not complete(p)]
            late={a['project_id'] for a in alerts if a['level']=='atrasado' and any(p['id']==a['project_id'] for p in active)}
            completed=[p for p in items if complete(p) and all(s['completed_at'] for s in p['sectors']) and max(s['completed_at'] for s in p['sectors'])[:7]==date.today().isoformat()[:7]]
            corrections=[]
            seen_events=set()
            for pid,created,action,payload in db.execute('SELECT project_id,created,action,payload FROM flow_events ORDER BY created DESC LIMIT 500'):
                signature=(pid,created,action,payload)
                if signature in seen_events:continue
                seen_events.add(signature)
                if pid in projects:
                    event={'created':created,'action':action,'payload':json.loads(payload)}
                    projects[pid].setdefault('history',[]).append(event)
                    if action=='request_correction':corrections.append({'project_id':pid,'message':event['payload']['message'],'created':created})
            return {'projects':items,'active':len(active),'late':len(late),'completed_this_month':len(completed),'by_sector':counts,'sectors':[{'id':sid,'name':name} for sid,name in sectors],'alerts':alerts,'correction_requests':corrections,'restricted_available':False,'revision':self.store.board_row(db)[0]}
