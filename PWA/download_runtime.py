"""Dependência fixa, local e verificável; não é executado pelo aplicativo."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent
BASE='https://cdn.jsdelivr.net/pyodide/v0.27.7/full/'

def download():
    vendor=ROOT/'vendor';vendor.mkdir(exist_ok=True)
    if not (vendor/'pyodide-lock.json').exists():(vendor/'pyodide-lock.json').write_bytes(urlopen(BASE+'pyodide-lock.json',timeout=60).read())
    lock=json.loads((vendor/'pyodide-lock.json').read_text(encoding='utf-8'))
    pinned=json.loads((ROOT/'RUNTIME-SHA256.json').read_text(encoding='utf-8')) if (ROOT/'RUNTIME-SHA256.json').exists() else {}
    selected=set()
    def include(name):
        if name in selected:return
        selected.add(name)
        for dependency in lock['packages'][name]['depends']:include(dependency)
    for name in ['sqlite3','hashlib']:include(name)
    files={name:None for name in ['pyodide.js','pyodide.asm.js','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']}
    for name in selected:
        info=lock['packages'][name];files[info['file_name']]=info['sha256']
    manifest={}
    for name,checksum in files.items():
        target=vendor/name
        if not target.exists():target.write_bytes(urlopen(BASE+name,timeout=120).read())
        sha=hashlib.sha256(target.read_bytes()).hexdigest()
        if (checksum and checksum!=sha) or (name in pinned and pinned[name]['sha256']!=sha):raise ValueError('Runtime divergente: '+name)
        manifest[name]={'sha256':sha,'bytes':target.stat().st_size,'source':BASE+name}
    xhr=vendor/'xhr-shim.js'
    xhr_source='https://cdn.jsdelivr.net/npm/xhr-shim@0.1.3/src/index.js'
    if not xhr.exists():xhr.write_bytes(urlopen(xhr_source,timeout=30).read())
    xhr_sha=hashlib.sha256(xhr.read_bytes()).hexdigest()
    if 'xhr-shim.js' in pinned and pinned['xhr-shim.js']['sha256']!=xhr_sha:raise ValueError('Adaptador XHR divergente.')
    manifest['xhr-shim.js']={'sha256':xhr_sha,'bytes':xhr.stat().st_size,'source':xhr_source}
    (ROOT/'RUNTIME-SHA256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(manifest),'bytes':sum(x['bytes'] for x in manifest.values()),'packages':sorted(selected)}))

if __name__=='__main__':download()
