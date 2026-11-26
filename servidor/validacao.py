"""Validação independente da interface antes de qualquer gravação."""
from datetime import date
import json
import math
import unicodedata

TYPES = {'status', 'attachments', 'text', 'people', 'timeline', 'date', 'dependency', 'number', 'action'}
FIXED = {'work': 'text', 'owner': 'people', 'deadline': 'date', 'summary': 'status', 'actions': 'action'}
MAX_WORKS, MAX_COLUMNS, MAX_BYTES = 1000, 100, 2_000_000


class InvalidState(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise InvalidState(message)


def text(value, limit=1000, empty=True):
    need(isinstance(value, str) and len(value) <= limit and '\x00' not in value, 'Texto inválido ou longo demais.')
    need(empty or bool(value.strip()), 'Texto obrigatório ausente.')
    return value


def key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.strip()) if not unicodedata.combining(c)).casefold()


def day(value):
    try:
        return isinstance(value, str) and len(value) == 10 and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def strings(values, limit=100):
    need(isinstance(values, list) and len(values) <= limit, 'Lista inválida.')
    for value in values:
        text(value, 120, empty=False)
    need(len(values) == len(set(values)), 'Valores repetidos na configuração.')
    return values


def validate(state):
    need(isinstance(state, dict) and state.get('schema') == 1, 'Formato de dados incompatível.')
    descriptions=state.get('labelDescriptions', {})
    need(isinstance(descriptions,dict) and len(descriptions)<=200, 'Descrições de etiquetas inválidas.')
    for label,description in descriptions.items():
        text(label,120,empty=False);text(description,300)
    required = {'materials', 'fixedHeaders', 'stages', 'customColors', 'excluded', 'summaryStages', 'summaryColors', 'summaryDone', 'summaryDefaults', 'defaults', 'purchased', 'rows', 'nextId', 'columnSequence', 'viewColumns', 'typeValues', 'deletedColumns', 'filters'}
    need(required <= state.keys(), 'Dados incompletos; nada foi gravado.')
    stages, summary = strings(state['stages']), strings(state['summaryStages'])
    need(stages and summary, 'É necessário manter as etiquetas.')
    strings(state['materials'])
    for name, allowed in [('excluded', stages), ('purchased', stages), ('summaryDone', summary)]:
        need(set(strings(state[name])) <= set(allowed), 'Classificação de etiqueta inválida.')
    need(not set(state['excluded']) & set(state['purchased']), 'Etiqueta não pode indicar material ausente e comprado ao mesmo tempo.')
    for name, allowed in [('defaults', stages), ('summaryDefaults', summary)]:
        need(isinstance(state[name], dict) and len(state[name]) <= 10, 'Configuração inválida.')
        need(all(v in allowed for v in state[name].values()), 'Etiqueta padrão inexistente.')
    need({'notStarted', 'notApplicable', 'approval'} <= state['defaults'].keys(), 'Etiquetas padrão incompletas.')
    need({'pending', 'done', 'empty'} <= state['summaryDefaults'].keys(), 'Resumo incompleto.')
    for name, allowed in [('customColors', stages), ('summaryColors', summary)]:
        pairs = state[name]
        need(isinstance(pairs, list) and len(pairs) <= 100, 'Cores inválidas.')
        seen = set()
        for pair in pairs:
            need(isinstance(pair, list) and len(pair) == 2, 'Cor inválida.')
            label, color = pair
            need(label in allowed and label not in seen, 'Etiqueta da cor inválida.')
            need(isinstance(color, str) and len(color) == 7 and color[0] == '#' and all(c in '0123456789abcdefABCDEF' for c in color[1:]), 'Cor inválida.')
            seen.add(label)
    headers = state['fixedHeaders']
    need(isinstance(headers, dict) and set(headers) == set(FIXED), 'Cabeçalhos fixos inválidos.')
    for value in headers.values():
        text(value, 120, empty=False)
    columns = state['viewColumns']
    need(isinstance(columns, list) and 5 <= len(columns) <= MAX_COLUMNS, 'Quantidade de colunas inválida.')
    column_ids, names = set(), set()
    deleted = set(strings(state['deletedColumns']))
    fixed = set()
    for column in columns:
        need(isinstance(column, dict), 'Coluna inválida.')
        cid = text(column.get('id'), 120, empty=False)
        need(cid not in column_ids, 'Identificador de coluna repetido.')
        column_ids.add(cid)
        need(column.get('kind') in {'fixed', 'material', 'extra'} and column.get('type') in TYPES and column.get('originalType') in TYPES, 'Tipo de coluna inválido.')
        name = text(column.get('key'), 120, empty=False)
        if column.get('role') == 'project_code':
            need(column['type']=='text', 'O código central deve manter o tipo Texto.')
        if column['kind'] == 'fixed':
            need(name in FIXED and cid == 'fixed-' + name and column['originalType'] == FIXED[name], 'Identidade da coluna fixa inválida.')
            fixed.add(name)
            name = headers[name]
        need(key(name) not in names, 'Nome de coluna repetido.')
        names.add(key(name))
        need(type(column.get('deleted', False)) is bool, 'Estado da coluna inválido.')
        if cid == 'fixed-work':
            need(column['type'] == 'text' and not column.get('deleted', False) and cid not in deleted, 'A coluna da obra deve permanecer visível, fixa e do tipo Texto.')
    need(fixed == set(FIXED) and columns[0]['id'] == 'fixed-work', 'As colunas de referência devem ser preservadas e a obra deve ficar primeiro.')
    need(deleted <= column_ids, 'Histórico de exclusão inválido.')
    works = state['rows']
    need(isinstance(works, list) and len(works) <= MAX_WORKS, 'Quantidade de obras inválida.')
    work_ids, references = set(), set()
    for row in works:
        need(isinstance(row, dict) and type(row.get('id')) is int and 0 < row['id'] < 2**31, 'Identificador da obra inválido.')
        need(row['id'] not in work_ids, 'Identificador de obra repetido.')
        work_ids.add(row['id'])
        for field, limit in [('work', 120), ('reference', 50), ('owner', 100)]:
            text(row.get(field), limit, empty=False)
        need(key(row['reference']) not in references, 'Número de romaneio repetido.')
        references.add(key(row['reference']))
        text(row.get('notes', ''), 1000)
        need(day(row.get('received')) and day(row.get('deadline')) and row['deadline'] >= row['received'], 'Período da obra inválido.')
        need(row.get('summary') is None or row['summary'] in summary, 'Status geral desconhecido.')
        if 'projectCode' in row: text(row['projectCode'],50,empty=False)
        limits=row.get('deadlineThresholds',[7,3])
        need(isinstance(limits,list) and len(limits)==2 and all(type(n) is int for n in limits) and 0<=limits[1]<=limits[0]<=365, 'Limites de alertas inválidos.')
        labels = row.get('labels')
        need(isinstance(labels, dict) and len(labels) <= MAX_COLUMNS * 2, 'Etiquetas da obra inválidas.')
        for material, label in labels.items():
            text(material, 120, empty=False)
            need(label in stages, 'Etiqueta desconhecida.')
        for column in columns:
            if column['type'] == 'status' and not (column['kind'] == 'fixed' and column['key'] == 'summary'):
                need(column['key'] in labels, 'Célula de status ausente.')
    need(type(state['nextId']) is int and state['nextId'] > max(work_ids, default=0), 'Sequência de obras inválida.')
    need(type(state['columnSequence']) is int and 0 < state['columnSequence'] < 2**31, 'Sequência de colunas inválida.')
    values = state['typeValues']
    need(isinstance(values, list) and len(values) <= MAX_COLUMNS, 'Valores das colunas inválidos.')
    seen_columns, dependencies = set(), {}
    columns_by_id = {c['id']: c for c in columns}
    for item in values:
        need(isinstance(item, list) and len(item) == 2, 'Valores de coluna inválidos.')
        cid, by_row = item
        need(cid in column_ids and cid not in seen_columns, 'Coluna dos valores inexistente ou repetida.')
        seen_columns.add(cid)
        need(isinstance(by_row, list) and len(by_row) <= MAX_WORKS, 'Valores de obra inválidos.')
        seen_rows = set()
        for row_item in by_row:
            need(isinstance(row_item, list) and len(row_item) == 2, 'Valores de obra inválidos.')
            rid, by_type = row_item
            need(type(rid) is int and rid in work_ids and rid not in seen_rows, 'Obra dos valores inexistente ou repetida.')
            seen_rows.add(rid)
            need(isinstance(by_type, list) and len(by_type) <= len(TYPES), 'Tipos dos valores inválidos.')
            seen_types = set()
            for typed in by_type:
                need(isinstance(typed, list) and len(typed) == 2, 'Valor inválido.')
                kind, value = typed
                need(kind in TYPES - {'status', 'action'} and kind not in seen_types, 'Tipo de valor inválido.')
                seen_types.add(kind)
                if kind in {'text', 'people'}:
                    text(value)
                elif kind == 'number':
                    need(value == '' or type(value) in {int, float} and math.isfinite(value), 'Número inválido.')
                elif kind == 'date':
                    need(value == '' or day(value), 'Data inválida.')
                elif kind == 'timeline':
                    need(value == '' or isinstance(value, dict) and set(value) == {'start', 'end'} and day(value['start']) and day(value['end']) and value['end'] >= value['start'], 'Cronograma inválido.')
                elif kind == 'dependency':
                    need(value == '' or isinstance(value, str) and value.isdigit() and int(value) in work_ids and int(value) != rid, 'Dependência inválida.')
                    if value and columns_by_id[cid]['type'] == kind and not columns_by_id[cid].get('deleted'):
                        dependencies.setdefault(rid, []).append(int(value))
    visited, visiting = set(), set()
    def visit(rid):
        need(rid not in visiting, 'Dependência circular.')
        if rid in visited:
            return
        visiting.add(rid)
        for target in dependencies.get(rid, []):
            visit(target)
        visiting.remove(rid)
        visited.add(rid)
    for rid in work_ids:
        visit(rid)
    filters = state['filters']
    need(isinstance(filters, dict) and set(filters) == {'search', 'material', 'stage'}, 'Filtros inválidos.')
    text(filters['search'], 1000)
    text(filters['material'], 120)
    need(filters['stage'] == '' or filters['stage'] in stages, 'Filtro de etapa inválido.')
    encoded = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    need(len(encoded.encode('utf-8')) <= MAX_BYTES, 'O quadro ultrapassou o limite local de dados.')
    return state
