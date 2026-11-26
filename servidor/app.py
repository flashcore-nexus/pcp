"""API local e entrega explícita da interface; não serve pastas privadas."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit, unquote, quote, parse_qs
import re
from .anexos import Documents
from .setores import Sectors
from .obras import Works
from .fluxo import Flow
from .armazenamento import Store, Conflict
from .validacao import InvalidState, MAX_BYTES

ROOT = Path(__file__).resolve().parent.parent


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, data_dir, seed=None):
        self.store = Store(data_dir, seed if seed is not None else json.loads((ROOT / 'servidor/seed.json').read_text(encoding='utf-8')))
        self.store.daily_backup()
        self.documents = Documents(self.store)
        self.sectors = Sectors(self.store)
        self.works = Works(self.store)
        self.flow = Flow(self.store)
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = 'PCP', ''
    def allowed_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def sector_param(self):
        values = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get('sector')
        if values is None:
            return None
        if len(values) != 1 or not values[0]:
            raise ValueError('Identificador de setor inválido.')
        return values[0]

    def check_cell_sector(self, cid):
        selected = self.sector_param()
        if selected is not None:
            with self.server.store.connect() as db:
                selected = self.server.store.require_sector(db, selected)
                row = db.execute('SELECT b.sector_id FROM cells c JOIN board_columns b ON b.id=c.column_id WHERE c.id=?', (cid,)).fetchone()
                if not row or row[0] != selected:
                    raise LookupError('Anexo não pertence ao setor selecionado.')

    def reply(self, status, body, content_type='application/json; charset=utf-8', disposition=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        if disposition:
            self.send_header('Content-Disposition', disposition)
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed_host():
            return self.reply(403, {'error': 'Endereço local não permitido.'})
        path = urlsplit(self.path).path
        if path == '/api/health':
            return self.reply(200, {'application': 'PCP', 'api': 1, 'storage': 'sqlite', 'uploads_enabled': self.server.documents.config().get('uploads_enabled', False)})
        if path in {'/api/flow','/api/overview'}:
            try:
                return self.reply(200,self.server.flow.overview() if path=='/api/overview' else self.server.flow.listing(self.sector_param()))
            except ValueError as error:
                return self.reply(400,{'error':str(error)[:300]})
            except Exception:
                return self.reply(500,{'error':'Não foi possível carregar o fluxo de setores.'})
        shared=re.fullmatch(r'/api/flow/files/([\w-]+)/([\w-]+)',path)
        if shared:
            try:
                name,data,mime=self.server.flow.shared_content(*shared.groups(),self.sector_param())
                return self.reply(200,data,mime,"attachment; filename*=UTF-8''"+quote(name,safe=''))
            except (ValueError,LookupError) as error:
                return self.reply(404,{'error':str(error)[:300]})
            except Exception:
                return self.reply(500,{'error':'Não foi possível confirmar o documento compartilhado.'})
        if path in {'/api/state', '/api/sectors', '/api/works'}:
            try:
                if path == '/api/sectors':
                    return self.reply(200, self.server.sectors.listing())
                if path == '/api/works':
                    return self.reply(200, self.server.works.listing())
                with self.server.store.connect() as db:
                    db.execute('BEGIN')
                    sector = self.server.store.require_sector(db, self.sector_param())
                    row = self.server.store.board_row(db, sector)
                    index = self.server.works.listing(db)
                return self.reply(200, {'revision': row[0], 'state': json.loads(row[1]), 'updated': row[2], 'csrf': self.server.token, 'works': index})
            except (ValueError, TypeError) as error:
                return self.reply(400, {'error': str(error)[:300]})
            except Exception:
                return self.reply(500, {'error': 'Não foi possível carregar o setor.'})
        if path == '/api/attachments':
            try:
                return self.reply(200, self.server.documents.listing(self.sector_param()))
            except (ValueError, TypeError) as error:
                return self.reply(400, {'error': str(error)[:300]})
            except Exception:
                return self.reply(500, {'error': 'Não foi possível carregar os anexos.'})
        match = re.fullmatch(r'/api/cells/([\w-]+)/attachments/([\w-]+)/(download|preview)', path)
        if match:
            try:
                cid, did, action = match.groups()
                self.check_cell_sector(cid)
                item, data, mime = self.server.documents.content(cid, did, action == 'preview')
                mode = 'inline' if action == 'preview' else 'attachment'
                return self.reply(200, data, mime, mode + "; filename=\"anexo" + Path(item['name']).suffix.lower() + "\"; filename*=UTF-8''" + quote(item['name'], safe=''))
            except LookupError as error:
                return self.reply(404, {'error': str(error)})
            except ValueError as error:
                return self.reply(400, {'error': str(error)})
            except Exception:
                return self.reply(500, {'error': 'Não foi possível ler o arquivo íntegro do disco.'})
        files = {'/static/fluxo.js': ('interface/static/fluxo.js', 'text/javascript; charset=utf-8'), '/static/obras.js': ('interface/static/obras.js', 'text/javascript; charset=utf-8'), '/static/setores.js': ('interface/static/setores.js', 'text/javascript; charset=utf-8'), '/static/anexos.js': ('interface/static/anexos.js', 'text/javascript; charset=utf-8'), '/': ('interface/index.html', 'text/html; charset=utf-8'), '/index.html': ('interface/index.html', 'text/html; charset=utf-8'), '/static/app.js': ('interface/static/app.js', 'text/javascript; charset=utf-8'), '/static/persistencia.js': ('interface/static/persistencia.js', 'text/javascript; charset=utf-8'), '/static/app.css': ('interface/static/app.css', 'text/css; charset=utf-8')}
        if path not in files:
            return self.reply(404, {'error': 'Recurso não disponível.'})
        filename, mime = files[path]
        try:
            self.reply(200, (ROOT / filename).read_bytes(), mime)
        except OSError:
            self.reply(500, {'error': 'Não foi possível carregar a interface.'})

    def do_POST(self):
        if not self.allowed_host():
            return self.reply(403, {'error': 'Endereço local não permitido.'})
        expected_origin = 'http://' + self.headers.get('Host', '')
        if self.headers.get('Origin') != expected_origin or not secrets.compare_digest(self.headers.get('X-PCP-CSRF', ''), self.server.token):
            return self.reply(403, {'error': 'Formulário não autorizado. Reabra o PCP pelo endereço local.'})
        path = urlsplit(self.path).path
        attachment = re.fullmatch(r'/api/cells/([\w-]+)/attachments(?:/([\w-]+)/(rename|delete))?', path)
        if attachment:
            return self.attachment_post(attachment)
        if path not in {'/api/state', '/api/sectors', '/api/works','/api/flow'}:
            return self.reply(404, {'error': 'Operação não disponível nesta etapa.'})
        if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
            return self.reply(415, {'error': 'Formato não permitido.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BYTES:
                return self.reply(413, {'error': 'Dados acima do limite local.'})
            self.connection.settimeout(10)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Dados incompletos.')
            payload = json.loads(body.decode('utf-8'))
            if path == '/api/flow':
                result = self.server.flow.mutate(payload,self.sector_param())
            elif path == '/api/works':
                result = self.server.works.mutate(payload, self.sector_param())
            elif path == '/api/sectors':
                result = self.server.sectors.mutate(payload)
            else:
                result = self.server.store.save(payload['state'], payload['revision'], sector_id=self.sector_param())
            self.reply(200, result)
        except Conflict as error:
            self.reply(409, {'error': str(error)})
        except (InvalidState, ValueError, KeyError, TypeError, RecursionError) as error:
            self.reply(400, {'error': str(error)[:300]})
        except Exception:
            self.reply(500, {'error': 'O armazenamento não confirmou a gravação. Mantenha esta aba aberta e tente novamente.'})

    def attachment_post(self, match):
        try:
            cid, did, action = match.groups()
            self.check_cell_sector(cid)
            limit = self.server.documents.config()['max_file_bytes'] if did is None else 4096
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != ('application/octet-stream' if did is None else 'application/json'):
                return self.reply(415, {'error': 'Formato de envio não permitido.'})
            if not 0 < length <= limit:
                return self.reply(413, {'error': 'Arquivo vazio ou acima do limite configurado.'})
            self.connection.settimeout(30)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Envio incompleto; tente novamente.')
            if did is None:
                name = unquote(self.headers.get('X-PCP-Filename', ''), errors='strict')
                result = self.server.documents.upload(cid, name, body)
            else:
                result = self.server.documents.change(cid, did, action, json.loads(body.decode('utf-8')))
            self.reply(201 if did is None else 200, result)
        except LookupError as error:
            self.reply(404, {'error': str(error)})
        except (ValueError, KeyError, TypeError) as error:
            self.reply(400, {'error': str(error)[:300]})
        except Exception:
            self.reply(500, {'error': 'O disco não confirmou a operação com o anexo. Tente novamente.'})

    def do_PUT(self):
        self.reply(405, {'error': 'Método não permitido.'})
    do_DELETE = do_PUT

    def log_message(self, fmt, *args):
        # Não registra corpo, token ou parâmetros de pesquisa da página.
        print(f'{self.log_date_time_string()} {self.command} {urlsplit(self.path).path}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8771)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'dados')
    options = parser.parse_args()
    with Server(('127.0.0.1', options.port), options.data_dir) as server:
        print(f'PCP com SQLite em http://127.0.0.1:{server.server_port}/', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
