"""Build por lista explícita: nenhum banco, documento, credencial ou backup é publicado."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
PCP=ROOT.parent
VERSION=sys.argv[1] if len(sys.argv)>1 else '1.0.0'
OUT=ROOT/'dist'
PY=['__init__.py','armazenamento.py','validacao.py','anexos.py','setores.py','obras.py','consolidacao.py','fluxo.py','prazos.py']

def build():
    # Limpeza restrita à saída gerada deste build, nunca ao PCP ou dados.
    if OUT.exists():
        if OUT.resolve().parent!=ROOT.resolve() or OUT.name!='dist':raise ValueError('Saída inválida.')
        shutil.rmtree(OUT)
    (OUT/'static').mkdir(parents=True);(OUT/'python/servidor').mkdir(parents=True);(OUT/'icons').mkdir()
    runtime=json.loads((ROOT/'RUNTIME-SHA256.json').read_text())
    for name,info in runtime.items():
        source=ROOT/'vendor'/name
        if hashlib.sha256(source.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Runtime divergente: '+name)
    (OUT/'vendor').mkdir()
    for name in runtime:shutil.copyfile(ROOT/'vendor'/name,OUT/'vendor'/name)
    for name in PY:shutil.copyfile(PCP/'servidor'/name,OUT/'python/servidor'/name)
    shutil.copyfile(ROOT/'src/bridge.py',OUT/'python/bridge.py')
    seed=json.loads((PCP/'servidor/seed.json').read_text(encoding='utf-8'))
    seed.update(rows=[],nextId=1,typeValues=[],filters={'search':'','material':'','stage':''})
    (OUT/'python/servidor/seed.json').write_text(json.dumps(seed,ensure_ascii=False),encoding='utf-8',newline='\n')
    for source in (PCP/'interface/static').iterdir():
        if source.suffix not in {'.js','.css'}:continue
        text=source.read_text(encoding='utf-8')
        for quote in ["'",'"']:
            text=text.replace(quote+'/api/',quote+'./api/').replace(quote+'/?sector=',quote+'./?sector=')
        text=text.replace("'/', '/?", "'./', './?")
        # A confirmação de gravação agora significa COMMIT + persistência IndexedDB.
        text=text.replace('SQLite local ·','Armazenamento do dispositivo ·').replace('neste computador','neste dispositivo').replace('do computador','do dispositivo').replace('no computador','no dispositivo')
        (OUT/'static'/source.name).write_text(text,encoding='utf-8',newline='\n')
    for name in ['boot.js','engine.js']:shutil.copyfile(ROOT/'src'/name,OUT/name)
    shutil.copytree(ROOT/'licenses',OUT/'licenses')
    html=(PCP/'interface/index.html').read_text(encoding='utf-8').replace('href="/static/','href="./static/').replace('src="/static/app.js"','src="./boot.js"')
    html=html.replace('<title>PCP · Compras</title>','<title>PCP — by FlashCore</title>')
    html=html.replace('<link rel="stylesheet"', '<link rel="manifest" href="./manifest.webmanifest"><meta name="theme-color" content="#13283f"><link rel="apple-touch-icon" href="./icons/icon-192.png"><link rel="stylesheet"',1)
    html=html.replace('PCP<small>Fluxos da empresa</small>','PCP<small>by FlashCore</small>')
    html=html.replace('<main class="page">','<main class="page"><section class="pwa-tools" aria-label="Aplicativo e backup"><span>PCP — by FlashCore · v'+VERSION+'</span><button id="pwa-install">Instalar</button><button id="pwa-check">Verificar atualização</button><button id="pwa-export">Exportar backup</button><button id="pwa-import">Importar backup</button><button id="pwa-about-open">Sobre</button><p id="pwa-status" role="status">Abrindo PCP…</p></section>',1)
    html=html.replace('</body>','<input type="file" accept=".zip" id="pwa-backup-file" hidden><dialog id="pwa-about"><h2>PCP — by FlashCore</h2><p>Versão '+VERSION+'. <span id="pwa-build"></span> Uso individual, offline após a preparação inicial. Os dados ficam neste navegador e dispositivo, sem sincronização automática.</p><p>Antes de limpar dados do navegador, trocar de endereço, perfil ou dispositivo, exporte um backup completo com anexos. Limites de espaço e retenção dependem do navegador; o modo privado não é recomendado.</p><button id="pwa-persist">Solicitar proteção do armazenamento</button><button id="pwa-about-close">Fechar</button></dialog></body>')
    html=html.replace('PCP local · exemplos fictícios.','PCP individual · armazenamento neste dispositivo.').replace('neste computador','neste dispositivo')
    (OUT/'index.html').write_text(html,encoding='utf-8',newline='\n')
    with (OUT/'static/app.css').open('a',encoding='utf-8',newline='\n') as css:css.write('\n.pwa-tools{padding:10px 14px;background:#fff;border:1px solid #dce5ef;border-radius:9px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:18px}.pwa-tools button{border:1px solid #dce5ef;border-radius:6px;background:#f8fafc;padding:8px;cursor:pointer}.pwa-tools p{flex-basis:100%;font-size:12px;margin:0}.pwa-tools>span{font-size:12px;font-weight:700}#pwa-about{max-width:580px}#pwa-about p{line-height:1.6}\n')
    iconroot=ROOT/'src/icons'
    icons=[]
    for name in ['icon-192.png','icon-512.png','icon-maskable-512.png']:
        shutil.copyfile(iconroot/name,OUT/'icons'/name)
        icons.append({'src':'./icons/'+name,'sizes':'192x192' if '192' in name else '512x512','type':'image/png','purpose':'maskable' if 'maskable' in name else 'any'})
    (OUT/'manifest.webmanifest').write_text(json.dumps({'id':'./','name':'PCP','short_name':'PCP','description':'Gestão individual de obras e setores — by FlashCore','lang':'pt-BR','start_url':'./','scope':'./','display':'standalone','theme_color':'#13283f','background_color':'#13283f','icons':icons},ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    (OUT/'.nojekyll').touch()
    files={str(p.relative_to(OUT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.rglob('*')) if p.is_file()}
    build_id=hashlib.sha256((VERSION+json.dumps(files,sort_keys=True)).encode()).hexdigest()[:20]
    (OUT/'version.json').write_text(json.dumps({'version':VERSION,'build':build_id,'schema':5,'backup_format':1}),encoding='utf-8',newline='\n')
    files['version.json']=hashlib.sha256((OUT/'version.json').read_bytes()).hexdigest()
    template=(ROOT/'src/sw-template.js').read_text(encoding='utf-8')
    constants='const BUILD='+json.dumps(build_id)+';\nconst FILES='+json.dumps(files,separators=(',',':'))+';\nconst PYTHON_FILES='+json.dumps([x for x in files if x.startswith('python/')])+';\n'
    imports="importScripts('./vendor/xhr-shim.js');self.XMLHttpRequest=self.XMLHttpRequestShim;importScripts('./vendor/pyodide.js','./vendor/pyodide.asm.js','./engine.js');\n"
    template=template.replace('/* BUILD_CONSTANTS */',constants+imports).replace('premium-frotas:','flashcore-pcp:')
    template=template.replace("if(event.request.mode==='navigate'){", "if(url.pathname.startsWith(new URL('api/',self.registration.scope).pathname)){event.respondWith(localAPI(event.request));return;}\n if(event.request.mode==='navigate'){")
    template=template.replace("if(event.request.method!=='GET'||url.origin", "if(url.origin")
    template=template.replace("const indexURL=new URL('./',self.registration.scope).href;", "const indexURL=new URL('./',self.registration.scope).href;\nconst networkFetch=self.fetch.bind(self);self.fetch=async(input,options)=>{const u=new URL(input instanceof Request?input.url:input,self.registration.scope);if(essential.has(u.href)){const cached=await(await caches.open(cacheName)).match(u.href);if(cached)return cached;}return networkFetch(input,options);};")
    # Navegação sem backend: a entrada da raiz é a mesma index.html verificada.
    template=template.replace('return await cache.match(indexURL)||fetch(event.request)', "return await cache.match(new URL('index.html',self.registration.scope).href)||fetch(event.request)")
    (OUT/'sw.js').write_text(template,encoding='utf-8',newline='\n')
    report={'version':VERSION,'build':build_id,'files':files,'sw_sha256':hashlib.sha256((OUT/'sw.js').read_bytes()).hexdigest(),'runtime_bytes':sum(p.stat().st_size for p in (OUT/'vendor').iterdir())}
    (ROOT/'BUILD-MANIFEST.json').write_text(json.dumps(report,indent=2),encoding='utf-8',newline='\n')
    print(json.dumps({'build':build_id,'files':len(files),'runtime_mb':round(report['runtime_bytes']/1048576,2)}))

if __name__=='__main__':build()
