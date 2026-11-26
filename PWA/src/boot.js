/* A interface só inicia quando todas as operações locais podem ser interceptadas. */
const status=document.getElementById('pwa-status');
const message=text=>{status.textContent=text};
let registration,installPrompt,attempting=false,frozen=false;
const shell=document.querySelector('.shell');shell.inert=true;
let transportBusy=0;
// Instrumenta o transporte, sem alterar as regras ou as respostas da aplicação.
const originalFetch=window.fetch.bind(window);
window.fetch=async(...args)=>{const local=String(args[0]?.url||args[0]).includes('api/');if(local)transportBusy++;try{return await originalFetch(...args)}finally{if(local)transportBusy--}};
const pending=()=>transportBusy>0||document.querySelector('[data-storage="saving"],[data-storage="error"]')||document.documentElement.dataset.storage==='saving'||document.documentElement.dataset.storage==='error'||[...document.querySelectorAll('dialog[open]')].some(d=>d.id!=='pwa-about');
function showUpdate(){
 if(!registration?.waiting)return;
 status.replaceChildren(document.createTextNode('Nova versão disponível. '));
 const update=document.createElement('button');update.textContent='Atualizar aplicativo';update.className='secondary';
 update.onclick=()=>{if(pending()){message('Finalize ou cancele as edições abertas antes de atualizar.');return;}attempting=true;registration.waiting.postMessage({type:'REQUEST_ACTIVATION'});};status.append(update);
}
function unlock(){frozen=false;shell.inert=false;}
navigator.serviceWorker?.addEventListener('message',event=>{
 const data=event.data||{};
 if(data.type==='PREPARE_UPDATE'){
  const ready=!pending();if(ready){frozen=true;shell.inert=true;}
  event.source.postMessage({type:'UPDATE_VOTE',nonce:data.nonce,ready});
 }
 if(data.type==='UPDATE_ABORTED'||data.type==='UPDATE_ERROR'){unlock();attempting=false;message('Atualização adiada. Conclua as operações em todas as abas e tente novamente.');}
});
navigator.serviceWorker?.addEventListener('controllerchange',()=>{if(attempting||frozen)location.reload()});
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event});
document.getElementById('pwa-install').onclick=async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;}else message('Instale pelo menu do Chrome/Edge. No iPhone: Safari → Compartilhar → Adicionar à Tela de Início.');};
document.getElementById('pwa-check').onclick=async()=>{try{await registration.update();if(registration.waiting)showUpdate();else message('A versão atual continua disponível; nenhuma atualização pronta.');}catch{message('Sem conexão para verificar. Seus dados e os recursos offline continuam disponíveis.');}};
document.getElementById('pwa-about-open').onclick=()=>document.getElementById('pwa-about').showModal();
document.getElementById('pwa-about-close').onclick=()=>document.getElementById('pwa-about').close();
document.getElementById('pwa-persist').onclick=async()=>{const granted=await navigator.storage?.persist?.();message(granted?'Armazenamento persistente autorizado neste navegador.':'O navegador não concedeu proteção adicional. Mantenha backups completos fora do navegador.');};
document.getElementById('pwa-export').onclick=async()=>{
 try{
  if(pending())throw Error('Finalize ou cancele as edições abertas antes de exportar.');
  message('Preparando backup completo com os anexos…');
  const r=await fetch('./api/backup');if(!r.ok)throw Error((await r.json()).error);
  const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='PCP-backup-'+new Date().toISOString().slice(0,10)+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);message('Backup completo preparado. Guarde o ZIP fora do navegador.');
 }catch(e){message(e.message)}
};
const input=document.getElementById('pwa-backup-file');
function confirmRestore(file){
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog'),title=document.createElement('h2'),text=document.createElement('p');
  title.textContent='Restaurar backup completo?';text.textContent='Arquivo: '+file.name+'. Os dados desta instalação serão substituídos somente após a validação. Uma cópia anterior será preservada.';
  const cancel=document.createElement('button'),confirm=document.createElement('button');cancel.textContent='Cancelar';confirm.textContent='Confirmar restauração';
  const finish=value=>{dialog.close();dialog.remove();resolve(value)};cancel.onclick=()=>finish(false);confirm.onclick=()=>finish(true);dialog.addEventListener('cancel',event=>{event.preventDefault();finish(false)});
  dialog.append(title,text,cancel,confirm);document.body.append(dialog);dialog.showModal();
 });
}
document.getElementById('pwa-import').onclick=()=>{if(pending()){message('Finalize ou cancele as edições abertas antes de importar.');return;}input.click();};
input.onchange=async()=>{
 const file=input.files[0];input.value='';if(!file)return;
 if(!await confirmRestore(file))return;
 shell.inert=true;
 try{
  if(file.size>512*1024*1024)throw Error('Backup acima do limite de 512 MB.');
  const state=await (await fetch('./api/state')).json();
  const result=await fetch('./api/restore',{method:'POST',headers:{'Content-Type':'application/zip','X-PCP-CSRF':state.csrf,'X-PCP-Confirm':'true'},body:file});
  const payload=await result.json();if(!result.ok)throw Error(payload.error);
  message('Backup restaurado. Reabra esta página para usar os dados importados.');
  shell.inert=false;
  // Mantém os quadros antigos bloqueados, mas permite baixar a recuperação e reabrir.
  document.querySelectorAll('.side, main.page > :not(.pwa-tools)').forEach(element=>element.inert=true);
  const recovery=document.createElement('a');recovery.href='./api/recovery?name='+encodeURIComponent(payload.recovery);recovery.download='PCP-antes-da-restauracao.zip';recovery.textContent=' Baixar cópia anterior';status.append(recovery);
  const reload=document.createElement('button');reload.textContent='Abrir dados restaurados';reload.onclick=()=>location.reload();status.append(reload);
 }catch(e){shell.inert=false;message('Restauração não confirmada. '+e.message);}
};
try{
 if(!isSecureContext||!navigator.serviceWorker||!window.indexedDB)throw Error('Abra por HTTPS ou pelo servidor de prévia. Este navegador precisa oferecer Service Worker e IndexedDB.');
 message('Preparando os recursos locais e offline. A primeira abertura pode demorar…');
 const scope=new URL('./',location.href).href;
 registration=await navigator.serviceWorker.getRegistration(scope);
 if(!registration||registration.scope!==scope)registration=await navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'});
 registration.addEventListener('updatefound',()=>{const worker=registration.installing;worker?.addEventListener('statechange',()=>{if(worker.state==='installed')showUpdate()})});
 await navigator.serviceWorker.ready;
 if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
 message('Abrindo o armazenamento deste dispositivo…');
 const health=await fetch('./api/health');if(!health.ok)throw Error((await health.json()).error);
 const version=await(await fetch('./version.json')).json();document.getElementById('pwa-build').textContent='Build '+version.build;
 if(registration.waiting)showUpdate();else message('PCP — by FlashCore · dados neste dispositivo. Mantenha backup externo.');
 shell.inert=false;await import('./static/app.js');
 if(navigator.onLine)registration.update().catch(()=>{});
}catch(error){message('Não foi possível preparar o aplicativo. '+error.message);document.getElementById('storage-status').textContent='Abertura não concluída';}
