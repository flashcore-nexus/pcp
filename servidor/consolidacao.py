"""Migração incremental v1: modelos de setor, código central e etapas manuais.

Aplicação explícita após backup; reabrir o Store nunca reaplica os modelos.
"""
import copy
from datetime import datetime, timezone
import json
import uuid
from .armazenamento import canonical, Conflict
from .validacao import validate, text, key, InvalidState

COLORS = ['#64748B', '#0F766E', '#1D4ED8', '#A16207', '#7C3AED', '#C2410C', '#15803D']
DESCRIPTIONS = [
    'O trabalho ainda não começou.', 'Atividade agendada ou pedido já programado.',
    'A equipe está executando esta atividade.', 'Depende de informação, aprovação ou material.',
    'O resultado está sendo conferido.', 'Necessita ajuste ou retrabalho antes de prosseguir.',
    'Esta atividade foi concluída. Não autoriza automaticamente a próxima etapa.'
]
# O segundo elemento identifica o significado universal (não a posição da etiqueta).
LABELS = {
    'Comercial': [('Rascunho',0),('Proposta enviada',1),('Em negociação',2),('Aguardando cliente',3),('Em revisão',4),('Em ajustes',5),('Vendido',6)],
    'Medição': [('Não iniciada',0),('Agendada',1),('Em execução',2),('Aguardando acesso',3),('Em conferência',4),('Remedição necessária',5),('Concluída',6)],
    'Projetos': [('Não iniciado',0),('Em andamento',2),('Aguardando informações',3),('Em conferência',4),('Em ajustes',5),('Concluído',6)],
    'Compras': [('Não iniciado',0),('Pedido emitido',1),('Em cotação',2),('Aguardando aprovação',3),('Conferindo recebimento',4),('Pedido em ajustes',5),('Recebido',6)],
    'Produção': [('Não iniciada',0),('Programada',1),('Em produção',2),('Aguardando material',3),('Em conferência',4),('Retrabalho',5),('Concluída',6)],
    'Instalação': [('Não iniciada',0),('Agendada',1),('Em instalação',2),('Aguardando liberação',3),('Em vistoria',4),('Ajustes pendentes',5),('Concluída',6)],
}
MODELS = {
    # Campos financeiros/restritos não são disponibilizados enquanto não houver autenticação.
    'Comercial': [('Documentos para Medição','attachments'),('Observações técnicas','text')],
    'Medição': [('Medição de contramarco','status'),('Medição final','status'),('Técnico responsável','people'),('Próxima visita','date'),('Relatórios de medição','attachments')],
    'Projetos': [('Projetista','people'),('Data de início','date'),('Arquivos do projeto','attachments')],
    'Compras': [('Perfis','status'),('Vidros','status'),('Telas','status'),('Acessórios','status'),('Romaneios e listas de materiais','attachments')],
    'Produção': [('Programação de início','date'),('Corte','status'),('Montagem','status'),('Conferência final','status'),('Acabamento','text'),('Peso bruto em kg','number'),('Cadernos de produção','attachments'),('Equipe responsável','people')],
    'Instalação': [('Equipe responsável','people'),('Data agendada','date'),('Vistoria / Aptidão','status'),('Materiais na obra','status'),('Data dos materiais na obra','date'),('Checklist final','status'),('Documentos e fotos','attachments')],
}


def manual_summary(state, row):
    # Congela uma única vez o resultado antigo. Depois disso o status é sempre manual.
    if row.get('summary') is not None:
        return row['summary']
    columns = [c for c in state['viewColumns'] if not c.get('deleted') and c['type']=='status' and c['kind']!='fixed']
    active = [row['labels'][c['key']] for c in columns if row['labels'][c['key']] not in state['excluded']]
    return state['summaryDefaults']['done' if active and all(v in state['purchased'] for v in active) else 'pending' if active else 'empty']


def prepare_board(source, name, empty=False):
    state=copy.deepcopy(source)
    if empty:
        state['rows']=[];state['typeValues']=[];state['deletedColumns']=[]
        state['viewColumns']=[copy.deepcopy(c) for c in source['viewColumns'] if c['kind']=='fixed']
        for c in state['viewColumns']:
            c['type']=c['originalType'];c.pop('deleted',None)
        state.update(materials=[], columnSequence=1)
    # Guarda etiquetas e cores personalizadas; modelos nunca substituem ocorrências existentes.
    labels=LABELS[name]
    for collection in ['stages','summaryStages']:
        for label,_ in labels:
            if label not in state[collection]:state[collection].append(label)
    for collection in ['customColors','summaryColors']:
        colors=dict(state[collection])
        for label,i in labels:
            colors[label]=COLORS[i]
        state[collection]=list(map(list,colors.items()))
    state.setdefault('labelDescriptions',{})
    for collection in ['stages','summaryStages']:
        for label in state[collection]:
            state['labelDescriptions'].setdefault(label, 'Etiqueta preservada do quadro anterior; personalize sua descrição.')
    for label,i in labels:state['labelDescriptions'][label]=DESCRIPTIONS[i]
    if empty:
        state.update(stages=[v for v,_ in labels]+['Não se aplica'],summaryStages=[v for v,_ in labels],
                     customColors=[[v,COLORS[i]] for v,i in labels]+[['Não se aplica','#64748B']],
                     summaryColors=[[v,COLORS[i]] for v,i in labels],excluded=['Não se aplica'],
                     purchased=[labels[-1][0]],summaryDone=[labels[-1][0]])
        state['defaults']={'notStarted':labels[0][0],'notApplicable':'Não se aplica','approval':next(v for v,i in labels if i==3)}
        state['summaryDefaults']={'pending':labels[0][0],'done':labels[-1][0],'empty':labels[0][0]}
    else:
        for row in state['rows']:row['summary']=manual_summary(state,row)
        if labels[-1][0] not in state['summaryDone']:state['summaryDone'].append(labels[-1][0])
        if labels[-1][0] not in state['purchased']:state['purchased'].append(labels[-1][0])
        state['summaryDefaults'].update(pending=labels[0][0],done=labels[-1][0],empty=labels[0][0])
    state['workflowVersion']=1
    state['fixedHeaders'].update(work='Obra / cliente',deadline='Prazo do setor',summary='Status comercial' if name=='Comercial' else 'Status geral da compra' if name=='Compras' else 'Status do setor')
    owner=next(c for c in state['viewColumns'] if c['id']=='fixed-owner')
    owner['deleted']=True
    if owner['id'] not in state['deletedColumns']:state['deletedColumns'].append(owner['id'])
    # Código central em coluna própria: reference continua sendo a identidade do romaneio.
    if not any(c.get('role')=='project_code' for c in state['viewColumns']):
        state['viewColumns'].insert(1,{'id':'v1-project-code','kind':'extra','key':'Código da obra','type':'text','originalType':'text','role':'project_code'})
    names={key(state['fixedHeaders'][c['key']] if c['kind']=='fixed' else c['key']) for c in state['viewColumns']}
    for title,kind in MODELS[name]:
        if key(title) in names:continue
        while any(c['id']=='custom-'+str(state['columnSequence']) for c in state['viewColumns']):state['columnSequence']+=1
        col={'id':'custom-'+str(state['columnSequence']),'kind':'extra','key':title,'type':kind,'originalType':kind}
        state['columnSequence']+=1;state['viewColumns'].insert(-1,col);names.add(key(title))
        if kind=='status':
            if title not in state['materials']:state['materials'].append(title)
            for row in state['rows']:row['labels'].setdefault(title,state['defaults']['notApplicable'])
    validate(state)
    return state


def migrate(store):
    """Backup é pré-condição; transação única e marcador só depois de tudo validado."""
    with store.connect() as db:
        if db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():return {'changed':False}
    backup=store.backup_full()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():return {'changed':False}
        now=datetime.now(timezone.utc).isoformat()
        from .fluxo import schema
        schema(db)
        db.execute('CREATE TABLE IF NOT EXISTS sector_models(sector_id TEXT PRIMARY KEY REFERENCES sectors(id),model TEXT NOT NULL UNIQUE)')
        db.execute('CREATE TABLE IF NOT EXISTS project_details(project_id TEXT PRIMARY KEY REFERENCES projects(id),code TEXT NOT NULL UNIQUE,information TEXT NOT NULL DEFAULT \'\')')
        for i,(pid,) in enumerate(db.execute('SELECT id FROM projects ORDER BY created,id').fetchall(),1):
            db.execute('INSERT OR IGNORE INTO project_details(project_id,code) VALUES (?,?)',(pid,'OBR-'+str(i).zfill(5)))
        primary=store.primary_sector(db)
        source=json.loads(store.board_row(db)[1]);revision=store.board_row(db)[0]+1
        existing=db.execute('SELECT id,name FROM sectors ORDER BY id').fetchall()
        chosen=set()
        for position,name in enumerate(MODELS):
            found=next(((sid,n) for sid,n in existing if key(n)==key(name)),None)
            sid=found[0] if found else str(uuid.uuid4());chosen.add(sid)
            if found:
                previous=json.loads(store.board_row(db,sid)[1]);state=prepare_board(previous,name)
            else:
                db.execute('INSERT INTO sectors VALUES (?,?,1)',(sid,name))
                db.execute('INSERT INTO sector_settings VALUES (?,?,?,?,?)',(sid,'','#315acb','▦',position))
                previous=None;state=prepare_board(source,name,empty=True)
            if name=='Comercial':
                for column in state['viewColumns']:
                    if column['key']=='Documentos para Medição':column['role']='technical_documents'
            db.execute('UPDATE sector_settings SET position=? WHERE id=?',(position,sid))
            db.execute('INSERT INTO sector_models VALUES (?,?)',(sid,name))
            for row in state['rows']:
                row['projectCode']=db.execute('SELECT d.code FROM project_details d JOIN work_links l ON l.project_id=d.project_id WHERE l.work_id=?',(row['id'],)).fetchone()[0]
            store.entities(db,state,previous,revision,now,sid,update_catalog=False)
            store.write_board(db,sid,state,now)
        extra=6
        for sid,_ in existing:
            if sid not in chosen:
                db.execute('UPDATE sector_settings SET position=? WHERE id=?',(extra,sid));extra+=1
                state=json.loads(store.board_row(db,sid)[1])
                for row in state['rows']:row['summary']=manual_summary(state,row)
                state['workflowVersion']=1
                store.write_board(db,sid,state,now)
        db.execute('UPDATE snapshot SET revision=?,updated=? WHERE id=1',(revision,now))
        db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='sector_revision'")
        db.execute("INSERT INTO meta VALUES ('consolidated_v1','1')")
        db.execute('PRAGMA user_version=5')
        db.execute('INSERT INTO audit(revision,created,entity,entity_id,action,after_data) VALUES (?,?,?,?,?,?)',(revision,now,'migration','v1','models_and_central_codes',canonical({'backup':str(backup)})))
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    return {'changed':True,'backup':str(backup),'revision':revision}


def normalize_codes(db, state, previous):
    """Mesmo código por obra, separado do identificador legado do romaneio."""
    if not db.execute("SELECT 1 FROM meta WHERE key='consolidated_v1'").fetchone():return
    old={r['id']:r for r in previous['rows']} if previous else {}
    links=dict(db.execute('SELECT work_id,project_id FROM work_links'))
    changes={}
    for row in state['rows']:
        pid=links.get(row['id'])
        if not pid:continue
        current=db.execute('SELECT code FROM project_details WHERE project_id=?',(pid,)).fetchone()[0]
        value=row.get('projectCode',current).strip()
        text(value,50,empty=False)
        if value!=old.get(row['id'],{}).get('projectCode',current):changes.setdefault(pid,set()).add(value)
    if any(len(v)>1 for v in changes.values()):raise InvalidState('Use um único código para a mesma obra.')
    for pid,values in changes.items():
        value=next(iter(values))
        if db.execute('SELECT 1 FROM project_details WHERE lower(code)=lower(?) AND project_id<>?',(value,pid)).fetchone():raise InvalidState('Código de obra já utilizado.')
        db.execute('UPDATE project_details SET code=? WHERE project_id=?',(value,pid))
    for row in state['rows']:
        if row['id'] in links:row['projectCode']=db.execute('SELECT code FROM project_details WHERE project_id=?',(links[row['id']],)).fetchone()[0]


if __name__=='__main__':
    from pathlib import Path
    from .armazenamento import Store
    root=Path(__file__).resolve().parent.parent
    print(json.dumps(migrate(Store(root/'dados',json.loads((root/'servidor/seed.json').read_text(encoding='utf-8')))),ensure_ascii=False))
