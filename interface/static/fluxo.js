// Comunicação explícita entre setores. Usa o mesmo servidor e os arquivos originais.
export function createFlow({persistence,attachments,sector,getRows,reload}) {
  const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  const sid=sector.id;
  let registry=[],data=null,busy=false;
  const notice=text=>{document.getElementById('message').textContent=text;};
  const dialog=make('dialog');dialog.id='flow-dialog';document.body.append(dialog);
  const heading=make('div',undefined,'dialoghead'),title=make('h2'),close=make('button','×','close');close.type='button';close.setAttribute('aria-label','Fechar');
  heading.append(title,close);dialog.append(heading);
  const body=make('div',undefined,'flow-body'),status=make('p');status.setAttribute('role','status');dialog.append(body,status);
  close.addEventListener('click',()=>{if(!busy)dialog.close();});dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  const tools=document.querySelector('.top > div:last-child');
  const inbox=make('button','Obras recebidas','secondary'),bell=make('button','🔔 Prazos','secondary');tools.prepend(inbox,bell);
  const overview=make('button','◉ Visão Geral','navitem sector-nav-button');overview.type='button';document.querySelector('.sector-navigation').prepend(overview);
  const sectorName=id=>registry.find(s=>s.id===id)?.name||id;
  const date=value=>new Date(value).toLocaleString('pt-BR');
  async function refresh() {data=await persistence.request('/api/flow');inbox.textContent='Obras recebidas ('+data.transfers.filter(t=>t.destination===sid&&!t.received).length+')';}
  async function prepare(name) {await persistence.ensureSaved();await refresh();title.textContent=name;body.replaceChildren();status.textContent='';if(!dialog.open)dialog.showModal();}
  function button(text,run,parent=body){const b=make('button',text,'secondary');b.type='button';b.addEventListener('click',()=>Promise.resolve(run()).catch(e=>{status.textContent=e.message;}));parent.append(b);return b;}
  async function mutate(payload) {
    if(busy)return;busy=true;body.inert=true;
    try {await persistence.ensureSaved();await refresh();data=await persistence.request('/api/flow',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,revision:data.revision,confirm:true})});await reload();await refresh();return true;}
    catch(e){status.textContent=e.message;return false;}
    finally {busy=false;body.inert=false;}
  }
  function fileLinks(transfer,container) {
    for(const f of transfer.files) {const a=make('a','📎 '+f.name+' · '+Math.ceil(f.size/1024)+' KB');a.href=f.url+'?sector='+encodeURIComponent(sid);container.append(a);}
    if(transfer.documentation_pending)container.append(make('p','Documentação pendente','late'));
  }
  async function showInbox() {
    await prepare('Obras recebidas e histórico');
    const received=data.transfers.filter(t=>t.destination===sid);
    if(!received.length)body.append(make('p','Nenhuma obra recebida neste setor.'));
    for(const t of received) {
      const card=make('section',undefined,'flow-card');const work=getRows().find(r=>r.id===t.record_id);
      card.append(make('h3',(work?.work||'Obra')+' · de '+sectorName(t.source)),make('p','Revisão '+t.version+' · '+date(t.created)),make('p',t.notes||'Sem observação encaminhada.'));
      fileLinks(t,card);
      if(!t.received)button('Confirmar recebimento',async()=>{if(await mutate({action:'receive',transfer_id:t.id}))await showInbox();},card);
      else card.append(make('p','Recebido em '+date(t.received),'muted'));
      button('Solicitar informação ou correção',async()=>{const message=prompt('Qual informação ou correção é necessária?');if(message?.trim()&&await mutate({action:'request_correction',transfer_id:t.id,message}))await showInbox();},card);
      body.append(card);
    }
    body.append(make('h3','Arquivados neste setor'));for(const row of getRows().filter(r=>r.archived)){const card=make('section',undefined,'flow-card');card.append(make('strong',row.work+' · '+(row.projectCode||row.reference)));button('Restaurar neste setor',async()=>{if(confirm('Restaurar este acompanhamento no setor?')&&await mutate({action:'restore_sector',record_id:row.id}))await showInbox();},card);body.append(card);}
    body.append(make('h3','Histórico deste setor'));
    const names={forward:'Encaminhamento',confirm_sale:'Venda confirmada',receive:'Recebimento',request_correction:'Solicitação de correção'};
    for(const event of data.events)body.append(make('p',date(event.created)+' · '+event.actor+' · '+(names[event.action]||event.action)+' · '+(event.payload.message||event.payload.notes||''),'flow-event'));
  }
  async function openForward(row) {
    await prepare('Encaminhar obra · '+row.work);
    const form=make('form');body.append(form);
    const sale=sector.model==='Comercial';
    if(sale)body.prepend(make('p','Confirmar venda mantém o registro comercial e envia os documentos técnicos selecionados à Medição. Não insira valores ou documentos comerciais restritos nesta versão.'));
    else body.prepend(make('p','A origem será preservada. Receber documentos não autoriza fabricação, compras ou gastos.'));
    const complete=make('input');complete.type='checkbox';const completeLabel=make('label');completeLabel.append(complete,make('span',' Marcar o status geral da origem como concluído'));if(!sale)form.append(completeLabel);
    const attachmentsData=await persistence.request('/api/attachments');
    const projectRecords=(await persistence.request('/api/works')).projects.find(p=>p.records.some(r=>r.id===row.id))?.records.map(r=>r.id)||[row.id];
    const sourceState=await persistence.request('/api/state');
    const choices=[];
    for(const target of registry.filter(s=>s.active&&s.id!==sid&&(!sale||s.model==='Medição'))) {
      const card=make('section',undefined,'flow-card');const selected=make('input');selected.type='checkbox';if(sale)selected.checked=true;
      const label=make('label');label.append(selected,make('strong',' '+target.name));card.append(label);
      const notes=make('textarea');notes.maxLength=1000;notes.placeholder='Observações técnicas autorizadas para este destino';notes.setAttribute('aria-label','Observações para '+target.name);card.append(notes);
      const files=[];
      for(const cell of attachmentsData.cells.filter(c=>projectRecords.includes(c.work_id))) {
        const column=sourceState.state.viewColumns.find(c=>c.id===cell.column_id);
        if(sale&&column?.role!=='technical_documents')continue;
        for(const file of cell.files) {const checkbox=make('input');checkbox.type='checkbox';const label=make('label');label.append(checkbox,make('span',' '+file.name+' · registro '+cell.work_id));card.append(label);files.push({checkbox,id:file.id});}
      }
      choices.push({selected,notes,files,id:target.id});form.append(card);
    }
    const submit=make('button',sale?'Confirmar venda e enviar à Medição':'Confirmar encaminhamento','primary');submit.type='submit';form.append(submit);
    form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;
      const destinations=choices.filter(c=>c.selected.checked).map(c=>({sector_id:c.id,notes:c.notes.value.trim(),documents:c.files.filter(f=>f.checkbox.checked).map(f=>f.id)}));
      if(!destinations.length){status.textContent='Escolha pelo menos um setor.';return;}
      if(!confirm((sale?'Confirmar venda':'Encaminhar a obra')+' para '+destinations.map(d=>sectorName(d.sector_id)).join(', ')+'? A origem será mantida.'))return;
      if(await mutate({action:sale?'confirm_sale':'forward',record_id:row.id,complete:complete.checked,destinations})){dialog.close();notice('Encaminhamento gravado. A origem foi preservada.');}
    });
    button('Arquivar somente neste setor',async()=>{if(confirm('Arquivar somente o acompanhamento deste setor? A obra, os outros setores e os anexos serão preservados.')&&await mutate({action:'archive_sector',record_id:row.id})){dialog.close();notice('Acompanhamento arquivado neste setor. Restaure em Obras recebidas.');}});
    const outgoing=data.transfers.filter(t=>t.source===sid&&projectRecords.includes(t.record_id));
    if(outgoing.length)body.append(make('p','Já encaminhada para: '+outgoing.map(t=>sectorName(t.destination)+' (revisão '+t.version+')').join(', '),'muted'));
  }
  async function showOverview() {
    await prepare('Visão Geral · consulta local');
    const all=await persistence.request('/api/overview');
    body.append(make('p',all.active+' obras ativas · '+all.late+' obras atrasadas · '+all.completed_this_month+' concluídas neste mês (com conclusão registrada). Uma contagem por obra. Sem informações financeiras.'));
    const unified=make('div',undefined,'flow-unified');
    const grid=make('div',undefined,'flow-unified-row');grid.style.gridTemplateColumns='minmax(180px,2fr) repeat('+all.sectors.length+',minmax(130px,1fr))';grid.append(make('strong','Obra / código'));
    for(const s of all.sectors)grid.append(make('strong',s.name+' ('+all.by_sector[s.id]+')'));
    unified.append(grid);
    for(const p of all.projects){const line=make('div',undefined,'flow-unified-row');line.style.gridTemplateColumns=grid.style.gridTemplateColumns;line.append(make('strong',p.code+' · '+p.name));for(const s of all.sectors){const tracks=p.sectors.filter(t=>t.id===s.id);line.append(make('span',tracks.length?[...new Set(tracks.map(t=>t.status+(t.deadline.level==='atrasado'?' · atrasado':'')))].join(' / '):'—',tracks.some(t=>t.deadline.level==='atrasado')?'late':''));}unified.append(line);}body.append(unified);
    for(const project of all.projects) {
      const details=make('details',undefined,'flow-card');details.append(make('summary',project.code+' · '+project.name));
      for(const track of project.sectors)details.append(make('p',track.name+' · '+track.status+' · '+(track.deadline.closed?'Contagem encerrada':track.deadline.days<0?Math.abs(track.deadline.days)+' dia(s) de atraso':track.deadline.days+' dia(s) restantes')));
      body.append(details);
    }
    if(!all.projects.length)body.append(make('p','Nenhuma obra ativa cadastrada.'));
    body.append(make('p','Consulta somente leitura do perfil pessoal. Conclusões antigas sem data registrada não são atribuídas a um período. Permissões por usuário e análise de gargalos ainda estão pendentes.','muted'));
    if(all.correction_requests.length){body.append(make('h3','Solicitações de informação e correção (histórico)'));for(const r of all.correction_requests)body.append(make('p',date(r.created)+' · '+r.message));}
  }
  async function related(row) {
    const area=document.getElementById('work-related');if(!area)return;
    area.replaceChildren(make('h3','Acompanhamento nos outros setores'));
    try {
      const all=await persistence.request('/api/overview');const project=all.projects.find(p=>p.sectors.some(s=>s.id===sid&&s.record_id===row.id));
      if(!project)return;
      for(const s of project.sectors){const entry=make('section',undefined,'flow-card');entry.append(make('strong',s.name+' · '+s.status),make('p','Prazo: '+s.deadline.date),make('p',s.notes||'Sem observações neste setor.'));area.append(entry);}
      for(const e of project.history||[])area.append(make('p',date(e.created)+' · '+e.action+' · '+(e.payload.message||e.payload.notes||''),'flow-event'));
    }catch(e){area.append(make('p',e.message,'error'));}
  }
  async function configureDeadline(row) {
    await prepare('Prazo do setor · '+row.work);row=getRows().find(r=>r.id===row.id);
    const all=await persistence.request('/api/overview');
    const project=all.projects.find(p=>p.sectors.some(t=>t.id===sid&&t.record_id===row.id));
    const form=make('form');body.append(form);
    function field(caption,element){const label=make('label',caption);label.append(element);form.append(label);return element;}
    const mode=field('Como definir o prazo',make('select'));
    for(const [value,name] of [['manual','Manualmente'],['after','Dias após a referência'],['before','Dias antes da referência']]){const o=make('option',name);o.value=value;mode.append(o);}
    const reference=field('Data de referência',make('select'));
    for(const track of project?.sectors||[])for(const [key,value] of Object.entries(track.dates)) {
      const option=make('option',track.name+' · registro '+track.record_id+' · '+(key==='received'?'Início':key==='deadline'?'Prazo':key)+' · '+value);
      option.value=JSON.stringify({sector:track.id,record:track.record_id,field:key});reference.append(option);
    }
    const days=field('Quantidade de dias',make('input'));days.type='number';days.min=0;days.max=3660;days.value=row.deadlineRule?.days??7;
    const business=field('Usar dias úteis',make('input'));business.type='checkbox';business.checked=row.deadlineRule?.business||false;
    const holidays=field('Feriados locais (AAAA-MM-DD, separados por vírgula)',make('textarea'));holidays.value=(row.deadlineRule?.holidays||[]).join(', ');holidays.maxLength=4100;
    const attention=field('Avisar atenção até quantos dias?',make('input'));attention.type='number';attention.min=0;attention.max=365;attention.value=row.deadlineThresholds?.[0]??7;
    const urgent=field('Avisar urgência até quantos dias?',make('input'));urgent.type='number';urgent.min=0;urgent.max=365;urgent.value=row.deadlineThresholds?.[1]??3;
    mode.value=row.deadlineRule?.mode||'manual';
    if(row.deadlineRule)reference.value=JSON.stringify({sector:row.deadlineRule.reference.sector,record:row.deadlineRule.reference.record,field:row.deadlineRule.reference.field});
    else reference.value=JSON.stringify({sector:sid,record:row.id,field:'received'});
    const submit=make('button','Salvar prazo','primary');submit.type='submit';form.append(submit);
    body.append(make('p','Dias úteis excluem sábado, domingo e os feriados informados acima. Mudanças na data referenciada recalculam o prazo. As etiquetas permanecem manuais.','muted'));
    form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;
      
      try {
        const limits=[Number(attention.value),Number(urgent.value)];
        if(!limits.every(Number.isInteger)||limits[1]<0||limits[0]<limits[1]||limits[0]>365)throw new Error('Confira os limites de atenção e urgência.');
        if(mode.value==='manual')delete row.deadlineRule;
        else {
          if(!reference.value)throw new Error('Escolha uma data de referência.');
          const offset=Number(days.value);if(!Number.isInteger(offset)||offset<0||offset>3660)throw new Error('Informe uma quantidade válida de dias.');
          row.deadlineRule={mode:mode.value,reference:JSON.parse(reference.value),days:offset,business:business.checked,holidays:holidays.value.split(',').map(v=>v.trim()).filter(Boolean)};
        }
        row.deadlineThresholds=limits;
        busy=true;body.inert=true;await persistence.ensureSaved();await reload();dialog.close();notice('Regra de prazo e alertas gravada.');
      }catch(e){status.textContent=e.message+' Se a gravação foi recusada, use Reabrir versão salva para retomar o quadro confirmado.';}
      finally{busy=false;body.inert=false;}
    });
  }
  async function showAlerts() {
    await prepare('Notificações de prazo');const all=await persistence.request('/api/overview');
    const alerts=all.alerts.filter(a=>a.sector===sector.name);
    if(!alerts.length)body.append(make('p','Nenhum prazo crítico neste setor.'));
    for(const a of alerts)body.append(make('p',a.work+' · '+a.message,a.level==='atrasado'?'late':'notice'));
    body.append(make('p','Lista atualizada por obra e setor, sem gerar notificações repetidas. Os status operacionais continuam manuais.','muted'));
  }
  for(const [element,action] of [[inbox,showInbox],[bell,showAlerts],[overview,showOverview]])element.addEventListener('click',()=>action().catch(e=>notice(e.message)));
  return {async start(){registry=(await persistence.request('/api/sectors')).sectors;await refresh();},openForward,configureDeadline,related};
}
