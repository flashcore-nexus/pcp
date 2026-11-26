"""Documentos privados: bytes imutáveis, identidade da célula e confirmação em disco."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import uuid
import zipfile

MIMES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.doc': 'application/msword', '.xls': 'application/vnd.ms-excel', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.dwg': 'application/acad', '.dxf': 'application/dxf', '.zip': 'application/zip'}
PREVIEW = {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}


def filename(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 180 or value != value.strip() or re.search(r'[\x00-\x1f\x7f<>:"/\\|?*]', value) or value.endswith('.'):
        raise ValueError('Nome de arquivo inválido (máximo 180 caracteres).')
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('Nome de arquivo reservado pelo Windows.')
    return value


def validate_file(name, data, config):
    extension = Path(filename(name)).suffix.lower()
    if extension not in MIMES or extension not in config['allowed_extensions']:
        raise ValueError('Extensão de arquivo não permitida.')
    if not data or len(data) > config['max_file_bytes']:
        raise ValueError('Arquivo vazio ou acima do limite configurado.')
    valid = False
    if extension == '.pdf': valid = data.startswith(b'%PDF-') and b'%%EOF' in data[-2048:]
    elif extension == '.png': valid = data.startswith(b'\x89PNG\r\n\x1a\n')
    elif extension in {'.jpg', '.jpeg'}: valid = data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')
    elif extension == '.webp': valid = data[:4] == b'RIFF' and data[8:12] == b'WEBP'
    elif extension in {'.doc', '.xls'}: valid = data.startswith(bytes.fromhex('d0cf11e0a1b11ae1'))
    elif extension == '.dwg': valid = re.match(rb'AC10[0-9]{2}', data) is not None
    elif extension == '.dxf': valid = data.startswith(b'AutoCAD Binary DXF') or re.search(rb'0\s+SECTION\s+2\s+(HEADER|ENTITIES|TABLES)', data[:8192], re.I) is not None
    elif extension in {'.zip', '.docx', '.xlsx'}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                valid = bool(names) and len(names) <= 10000
                if extension != '.zip':
                    required = 'word/document.xml' if extension == '.docx' else 'xl/workbook.xml'
                    valid = valid and '[Content_Types].xml' in names and required in names
                    valid = valid and not any(n.lower().endswith('vbaproject.bin') for n in names)
        except (zipfile.BadZipFile, ValueError): pass
    if not valid:
        raise ValueError('O conteúdo não corresponde ao formato informado ou está incompleto.')
    return extension


class Documents:
    def __init__(self, store):
        self.store = store

    def config(self):
        value = json.loads((self.store.directory / 'armazenamento.json').read_text(encoding='utf-8'))
        limit = value.get('max_file_bytes')
        if type(limit) is not int or not 0 < limit <= 100 * 1024 * 1024:
            raise ValueError('Limite de anexos inválido na configuração local (1 a 100 MB).')
        return {**value, 'max_files_per_cell': value.get('max_files_per_cell', 50)}

    def cell(self, db, cell_id):
        cell_id = str(uuid.UUID(cell_id))
        row = db.execute('SELECT c.id,c.work_id,c.column_id,b.metadata,b.sector_id FROM cells c JOIN board_columns b ON b.id=c.column_id WHERE c.id=?', (cell_id,)).fetchone()
        if not row:
            raise LookupError('Célula não disponível.')
        if db.execute('SELECT 1 FROM record_deletions WHERE work_id=?', (row[1],)).fetchone():
            raise LookupError('O romaneio está na lixeira. Restaure-o para acessar os anexos.')
        self.store.require_sector(db, row[4])
        state = json.loads(self.store.board_row(db, row[4])[1])
        column = json.loads(row[3])
        if column.get('restricted'):
            raise LookupError('Documentos restritos indisponíveis neste perfil local.')
        if column['id'] in state['deletedColumns']:
            raise LookupError('Célula não disponível.')
        if column['type'] not in {'status','attachments'} or column['kind'] == 'fixed':
            raise ValueError('Anexos disponíveis nas colunas Status + Anexos e Somente Anexos.')
        return row

    @staticmethod
    def metadata(row):
        return {'id': row[0], 'cell_id': row[1], 'name': row[2], 'size': row[3], 'sha256': row[4], 'created': row[5], 'preview': Path(row[2]).suffix.lower() in PREVIEW}

    def listing(self, sector_id=None):
        with self.store.connect() as db:
            sector_id = self.store.require_sector(db, sector_id)
            state = json.loads(self.store.board_row(db, sector_id)[1])
            cells = []
            deleted_records = {r[0] for r in db.execute('SELECT work_id FROM record_deletions')}
            by_cell = {}
            for document in db.execute('SELECT d.id,d.cell_id,d.original_name,d.size,d.sha256,d.created FROM documents d JOIN cells c ON c.id=d.cell_id JOIN board_columns b ON b.id=c.column_id WHERE d.deleted IS NULL AND b.sector_id=? ORDER BY d.created,d.id', (sector_id,)):
                by_cell.setdefault(document[1], []).append(self.metadata(document))
            for cid, wid, col, info in db.execute('SELECT c.id,c.work_id,c.column_id,b.metadata FROM cells c JOIN board_columns b ON b.id=c.column_id WHERE b.sector_id=?', (sector_id,)):
                column = json.loads(info)
                if not column.get('restricted') and column['id'] not in state['deletedColumns'] and column['type'] in {'status','attachments'} and column['kind'] != 'fixed' and wid not in deleted_records:
                    cells.append({'id': cid, 'work_id': wid, 'column_id': column['id'], 'files': by_cell.get(cid, [])})
        config = self.config()
        return {'cells': cells, 'config': {k: config[k] for k in ('uploads_enabled', 'max_file_bytes', 'max_files_per_cell', 'allowed_extensions')}}

    def audit(self, db, docid, action, before, after):
        db.execute('INSERT INTO audit(revision,created,entity,entity_id,action,before_data,after_data) VALUES ((SELECT revision FROM snapshot WHERE id=1),?,?,?,?,?,?)', (datetime.now(timezone.utc).isoformat(), 'document', docid, action, json.dumps(before, ensure_ascii=False) if before else None, json.dumps(after, ensure_ascii=False) if after else None))

    def upload(self, cid, name, data):
        config = self.config()
        if not config.get('uploads_enabled'):
            raise ValueError('Envio de arquivos desativado na configuração local.')
        validate_file(name, data, config)
        docid = str(uuid.uuid4())
        path = self.store.private_file_path(docid)
        created_file = False
        try:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                self.cell(db, cid)
                count = db.execute('SELECT count(*) FROM documents WHERE cell_id=? AND deleted IS NULL', (cid,)).fetchone()[0]
                if count >= config['max_files_per_cell']:
                    raise ValueError('Esta célula atingiu o limite de arquivos configurado.')
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as target:
                    created_file = True
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                checksum = hashlib.sha256(data).hexdigest()
                if path.stat().st_size != len(data) or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                    raise OSError('O disco não confirmou a integridade do arquivo.')
                now = datetime.now(timezone.utc).isoformat()
                db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,NULL)', (docid, cid, name, docid, len(data), checksum, now))
                result = self.metadata((docid, cid, name, len(data), checksum, now))
                self.audit(db, docid, 'upload', None, result)
            return result
        except Exception:
            if created_file:
                path.unlink(missing_ok=True)
            raise

    def get(self, db, cid, docid):
        self.cell(db, cid)
        docid = str(uuid.UUID(docid))
        row = db.execute('SELECT id,cell_id,original_name,size,sha256,created FROM documents WHERE id=? AND cell_id=? AND deleted IS NULL', (docid, cid)).fetchone()
        if not row:
            raise LookupError('Anexo não encontrado nesta célula.')
        return self.metadata(row)

    def content(self, cid, docid, preview=False):
        with self.store.connect() as db:
            item = self.get(db, cid, docid)
        if preview and not item['preview']:
            raise ValueError('Este formato está disponível apenas para baixar.')
        data = self.store.private_file_path(item['id']).read_bytes()
        if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise OSError('A integridade do anexo não foi confirmada.')
        return item, data, MIMES[Path(item['name']).suffix.lower()]

    def change(self, cid, docid, action, payload):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            before = self.get(db, cid, docid)
            if action == 'rename':
                name = filename(payload['name'])
                if Path(name).suffix.lower() != Path(before['name']).suffix.lower():
                    raise ValueError('Mantenha a extensão original ao renomear.')
                db.execute('UPDATE documents SET original_name=? WHERE id=?', (name, docid))
                after = {**before, 'name': name}
            elif action == 'delete':
                if payload.get('confirm') is not True:
                    raise ValueError('Confirme a exclusão do arquivo.')
                db.execute('UPDATE documents SET deleted=? WHERE id=?', (datetime.now(timezone.utc).isoformat(), docid))
                after = {'deleted': True}
            else:
                raise LookupError('Operação não disponível.')
            self.audit(db, docid, action, before, after)
        return after
