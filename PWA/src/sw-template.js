
/* BUILD_CONSTANTS */
const prefix='premium-frotas:'+self.registration.scope+':';
const cacheName=prefix+BUILD;
const essential=new Set(Object.keys(FILES).map(path=>new URL(path,self.registration.scope).href));
const indexURL=new URL('./',self.registration.scope).href;
self.addEventListener('install',event=>{
 event.waitUntil((async()=>{
  const cache=await caches.open(cacheName);
  try{
   for(const [path,hash] of Object.entries(FILES)){
    const response=await fetch(new Request(path,{cache:'no-store'}));
    if(!response.ok)throw new Error('Recurso indisponível');
    const bytes=await response.clone().arrayBuffer();
    const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
    if(digest!==hash)throw new Error('Recurso divergente');
    await cache.put(new URL(path,self.registration.scope).href,response);
   }
  }catch(error){await caches.delete(cacheName);throw error}
 })());
});
self.addEventListener('activate',event=>{
 event.waitUntil((async()=>{
  for(const name of await caches.keys())if(name.startsWith(prefix)&&name!==cacheName)await caches.delete(name);
  await self.clients.claim();
 })());
});
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(event.request.method!=='GET'||url.origin!==self.location.origin||!url.href.startsWith(self.registration.scope))return;
 if(event.request.mode==='navigate'){
  event.respondWith((async()=>{const cache=await caches.open(cacheName);return await cache.match(indexURL)||fetch(event.request)})());return;
 }
 if(essential.has(url.href))event.respondWith((async()=>{
  const cache=await caches.open(cacheName);
  return await cache.match(url.href)||new Response('Recurso offline indisponível. Reabra online.',{status:503});
 })());
});
let round=null;
self.addEventListener('message',event=>{
 const data=event.data||{};
 if(data.type==='UPDATE_VOTE'&&round?.nonce===data.nonce){
  if(round.clients.has(event.source?.id))round.votes.set(event.source.id,data.ready===true);
  if(round.votes.size===round.clients.size)round.resolve();
 }
 if(data.type!=='REQUEST_ACTIVATION'||round)return;
 event.waitUntil((async()=>{
  const clients=(await self.clients.matchAll({type:'window',includeUncontrolled:true})).filter(c=>c.url.startsWith(self.registration.scope));
  if(!clients.some(c=>c.id===event.source?.id))return;
  let resolve;
  const wait=new Promise(ok=>resolve=ok);
  round={nonce:crypto.randomUUID(),clients:new Set(clients.map(c=>c.id)),votes:new Map(),resolve};
  for(const client of clients)client.postMessage({type:'PREPARE_UPDATE',nonce:round.nonce});
  await Promise.race([wait,new Promise(ok=>setTimeout(ok,4000))]);
  const current=(await self.clients.matchAll({type:'window',includeUncontrolled:true})).filter(c=>c.url.startsWith(self.registration.scope));
  const ready=current.every(c=>round.votes.get(c.id)===true);
  if(ready)await self.skipWaiting();
  else for(const client of current)client.postMessage({type:'UPDATE_ABORTED'});
  round=null;
 })().catch(async()=>{for(const client of await self.clients.matchAll())client.postMessage({type:'UPDATE_ERROR'});round=null}));
});

