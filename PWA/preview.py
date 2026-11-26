"""Prévia estática: não abre o banco local nem expõe pastas privadas do PCP."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import functools
import http.client
import os

ROOT=Path(__file__).resolve().parent

def healthy():
    try:
        connection=http.client.HTTPConnection('127.0.0.1',8891,timeout=2)
        connection.request('GET','/dist/version.json');response=connection.getresponse();content=response.read();connection.close()
        return response.status==200 and b'"schema": 5' in content
    except OSError:return False

if __name__=='__main__':
    import subprocess,sys
    if not (ROOT/'dist/index.html').exists():subprocess.run([sys.executable,'-B',str(ROOT/'build.py')],check=True)
    if healthy():os.startfile('http://127.0.0.1:8891/dist/')
    else:
        handler=functools.partial(SimpleHTTPRequestHandler,directory=str(ROOT))
        with ThreadingHTTPServer(('127.0.0.1',8891),handler) as server:
            os.startfile('http://127.0.0.1:8891/dist/')
            server.serve_forever()
