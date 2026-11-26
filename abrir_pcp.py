"""Abre o PCP no Windows, iniciando somente o servidor local necessário."""
from contextlib import contextmanager
from datetime import datetime
import ctypes
import http.client
import json
import msvcrt
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import uuid

APP = Path(__file__).resolve().parent
RUNTIME = APP / 'dados' / 'inicializacao'
URL = 'http://127.0.0.1:8771/'


def healthy():
    connection = http.client.HTTPConnection('127.0.0.1', 8771, timeout=1)
    try:
        connection.request('GET', '/api/health')
        response = connection.getresponse()
        data = json.loads(response.read(131072)) if response.status == 200 else {}
        return data.get('application') == 'PCP' and data.get('api') == 1 and data.get('storage') == 'sqlite'
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def occupied():
    with socket.socket() as client:
        client.settimeout(1)
        return client.connect_ex(('127.0.0.1', 8771)) == 0


@contextmanager
def startup_lock():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / 'inicializacao.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'\0')
            handle.flush()
        deadline = time.monotonic() + 45
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Outra inicialização ainda está em andamento. Aguarde e tente novamente.')
                time.sleep(0.3)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def ensure_server():
    with startup_lock():
        if healthy():
            return {'servidor': 'ja_estava_ativo'}
        if occupied():
            raise RuntimeError('A porta 8771 está ocupada por outro serviço ou por uma inicialização incompleta. Nenhum processo foi encerrado.')
        python = Path(sys.base_prefix) / 'python.exe'
        if not python.is_file() or not (APP / 'interface' / 'index.html').is_file() or not (APP / 'servidor' / 'app.py').is_file():
            raise RuntimeError('Não encontrei os arquivos do PCP. Confira se a pasta do aplicativo foi movida.')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        log_path = RUNTIME / (stamp + '-servidor.log')
        with log_path.open('ab') as log:
            server = subprocess.Popen(
                [str(python), '-B', '-m', 'servidor.app', '--port', '8771'],
                cwd=APP, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        pid_path = APP / 'dados' / 'server.pid'
        if pid_path.exists():
            (RUNTIME / (stamp + '-pid-anterior.txt')).write_bytes(pid_path.read_bytes())
        pid_path.write_text(str(server.pid), encoding='ascii')
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if healthy():
                return {'servidor': 'iniciado', 'pid': server.pid, 'log': str(log_path)}
            if server.poll() is not None:
                raise RuntimeError('O servidor não conseguiu iniciar. Os detalhes estão em ' + str(log_path))
            time.sleep(0.3)
        raise RuntimeError('O servidor demorou para responder. Aguarde alguns segundos e tente abrir o atalho novamente. Log: ' + str(log_path))


def main():
    result = ensure_server()
    result['url'] = URL
    result['horario'] = datetime.now().astimezone().isoformat()
    with (RUNTIME / 'aberturas.jsonl').open('a', encoding='utf-8') as history:
        history.write(json.dumps(result, ensure_ascii=False) + '\n')
    if '--sem-navegador' not in sys.argv[1:]:
        os.startfile(URL)
    if sys.stdout is not None:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        try:
            RUNTIME.mkdir(parents=True, exist_ok=True)
            with (RUNTIME / 'erros.log').open('a', encoding='utf-8') as log:
                log.write(datetime.now().astimezone().isoformat() + '\n' + traceback.format_exc() + '\n')
        except OSError:
            pass
        if '--sem-navegador' in sys.argv[1:]:
            if sys.stderr is not None:
                print(str(error), file=sys.stderr)
        else:
            ctypes.windll.user32.MessageBoxW(None, str(error), 'PCP — não foi possível abrir', 0x10)
        sys.exit(1)
