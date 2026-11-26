"""Prazos derivados com referências explícitas, calendário local e detecção de ciclos."""
from datetime import date, timedelta
import copy
import json
from .validacao import InvalidState, validate, day


def shift(reference, days, business=False, holidays=()):
    result=date.fromisoformat(reference)
    direction=1 if days>=0 else -1
    for _ in range(abs(days)):
        result+=timedelta(days=direction)
        if business:
            while result.weekday()>=5 or result.isoformat() in holidays:result+=timedelta(days=direction)
    return result.isoformat()


def calculate(store,db,incoming,source,revision,now):
    """Calcula tudo antes de gravar; não altera etiquetas e não divide a transação."""
    states={source:incoming}
    before={}
    for (sid,) in db.execute('SELECT id FROM sectors'):
        if sid!=source:
            state=json.loads(store.board_row(db,sid)[1]);before[sid]=copy.deepcopy(state);states[sid]=state
    links=dict(db.execute('SELECT work_id,project_id FROM work_links'))
    rows={(sid,r['id']):r for sid,state in states.items() for r in state['rows']}
    visited=set();visiting=set()
    def resolve(sid,rid):
        identity=(sid,rid)
        if identity in visiting:raise InvalidState('Referência circular entre prazos.')
        if identity in visited:return rows[identity]['deadline']
        visiting.add(identity);row=rows[identity];rule=row.get('deadlineRule')
        if rule:
            if not isinstance(rule,dict) or rule.get('mode') not in {'after','before'}:raise InvalidState('Regra de prazo inválida.')
            offset=rule.get('days');business=rule.get('business',False);holidays=rule.get('holidays',[])
            if type(offset) is not int or not 0<=offset<=3660 or type(business) is not bool or not isinstance(holidays,list) or len(holidays)>366 or not all(day(d) for d in holidays):raise InvalidState('Calendário ou intervalo do prazo inválido.')
            ref=rule.get('reference',{})
            if not isinstance(ref,dict):raise InvalidState('Referência do prazo inválida.')
            target=(ref.get('sector'),ref.get('record'))
            if target not in rows or links.get(target[1])!=links.get(rid):raise InvalidState('Escolha uma referência da mesma obra.')
            field=ref.get('field')
            if field=='deadline':value=resolve(*target)
            elif field=='received':value=rows[target]['received']
            else:
                column=next((c for c in states[target[0]]['viewColumns'] if c['id']==field and c['type']=='date' and not c.get('deleted')),None)
                if not column:raise InvalidState('A coluna de data referenciada não está disponível.')
                typed=dict(dict(states[target[0]]['typeValues']).get(field,[]))
                value=dict(typed.get(target[1],[])).get('date','')
            if not day(value):raise InvalidState('Preencha a data de referência antes de calcular o prazo.')
            result=shift(value,offset if rule['mode']=='after' else -offset,business,holidays)
            if result<row['received']:raise InvalidState('O prazo calculado ficaria anterior ao início do setor.')
            row['deadline']=result
        visiting.remove(identity);visited.add(identity);return row['deadline']
    for sid,rid in rows:resolve(sid,rid)
    for sid,state in states.items():
        if sid!=source and state!=before[sid]:
            validate(state);store.entities(db,state,before[sid],revision,now,sid,update_catalog=False);store.write_board(db,sid,state,now)


def completion(state,previous,now):
    old={r['id']:r for r in previous['rows']} if previous else {}
    for row in state['rows']:
        was=old.get(row['id'],{})
        is_done=row.get('summary') in state['summaryDone']
        previously_done=was.get('summary') in (previous or state)['summaryDone']
        if is_done and not previously_done:row['completedAt']=now
        elif not is_done:row.pop('completedAt',None)
        elif 'completedAt' in was:row['completedAt']=was['completedAt']
        else:row.pop('completedAt',None) # Não inventa data para conclusões antigas.
