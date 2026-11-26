/* Executado somente pelo Service Worker, fora da interface. */
let runtimePromise=null, localQueue=Promise.resolve();
const syncFS=(py,populate)=>new Promise((resolve,reject)=>py.FS.syncfs(populate,error=>error?reject(error):resolve()));
async function runtime(){
 if(runtimePromise)return runtimePromise;
 runtimePromise=(async()=>{
  const py=await loadPyodide({indexURL:new URL('./vendor/',self.registration.scope).href});
  await py.loadPackage(['sqlite3','hashlib']);
  py.FS.mkdirTree('/code/servidor');
  for(const file of PYTHON_FILES){const response=await fetch(new URL(file,self.registration.scope));if(!response.ok)throw Error('Recurso local incompleto.');py.FS.writeFile('/code/'+file.replace('python/',''),new Uint8Array(await response.arrayBuffer()));}
  const mount='/device-'+encodeURIComponent(new URL(self.registration.scope).pathname).replace(/%/g,'_');
  py.FS.mkdirTree(mount);py.FS.mount(py.FS.filesystems.IDBFS,{},mount);await syncFS(py,true);
  py.globals.set('_data_path',mount+'/data');
  py.runPython("import sys\nsys.path.insert(0,'/code')\nimport bridge\nbridge.initialize(_data_path)");
  await syncFS(py,false);
  return py;
 })().catch(error=>{runtimePromise=null;throw error});
 return runtimePromise;
}
function localAPI(request){
 const operation=localQueue.then(async()=>{
  try{
   const py=await runtime(), url=new URL(request.url),root=new URL(self.registration.scope).pathname;
   const bytes=new Uint8Array(await request.arrayBuffer());
   if(bytes.byteLength>512*1024*1024)return Response.json({error:'Arquivo acima do limite de 512 MB.'},{status:413});
   py.globals.set('_method',request.method);py.globals.set('_path','/'+url.pathname.slice(root.length)+url.search);
   py.globals.set('_headers',JSON.stringify(Object.fromEntries(request.headers)));py.globals.set('_incoming',bytes);py.globals.set('_scope',root);
   const proxy=py.runPython("bridge.dispatch(_method,_path,bridge.json.loads(_headers),bytes(_incoming.to_py()),_scope)");
   let [status,headers,body]=proxy.toJs({dict_converter:entries=>Object.fromEntries(entries)});body=body.slice();proxy.destroy();py.globals.delete('_incoming');
   if(request.method==='POST'&&status>=400){if(status>=500||url.pathname.endsWith('/restore'))runtimePromise=null;}
   else await syncFS(py,false);
   return new Response(body,{status,headers:{...headers,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
  }catch(error){runtimePromise=null;return Response.json({error:'Não foi possível confirmar o armazenamento do dispositivo. Pode faltar espaço ou permissão. Preserve o backup e reabra o aplicativo. '+String(error.message).slice(0,180)},{status:507});}
 });
 localQueue=operation.catch(()=>{});return operation;
}
