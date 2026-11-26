// A visão da obra usa as próprias linhas/células do quadro e o mesmo gerenciador de anexos.
export function createWorkOverview({persistence, attachments, getRows, getColumns, getEditing, openEditor, renderCell, columnName, redraw, isDirty}) {
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => {const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e;};
  let index={projects:[],deleted_record_ids:[],batches:[]}, deleted=new Set(), busy=false;
  function setBusy(value) {busy=value;$('editor').inert=value;$('work-trash').inert=value;}
  const projectFor = rid => index.projects.find(p=>p.records.some(r=>r.id===rid));
  const notice = message => {$('work-action-message').textContent=message; $('work-trash-message').textContent=message; $('message').textContent=message;};
  function loaded(value) {
    if(!value)return;
    index=value;deleted=new Set(value.deleted_record_ids);
    const chosen=$('work-project').value;
    if($('editor').open&&getEditing()===null&&chosen&&$('work').readOnly) {
      const project=index.projects.find(p=>p.id===chosen);
      if(project){if(project.records.some(r=>!r.deleted))fillProjects(chosen);$('work').value=project.name;}
    }
  }
  async function refresh() {loaded(await persistence.request('/api/works'));redraw();renderTrash();}
  function fillProjects(selected='') {
    const select=$('work-project');select.replaceChildren(); const blank=make('option','Cadastrar uma nova obra');blank.value='';select.append(blank);
    for(const project of index.projects.filter(p=>p.records.some(r=>!r.deleted))) {const option=make('option',project.name+' · '+project.records.filter(r=>!r.deleted).length+' romaneio(s) · '+project.id.slice(0,8));option.value=project.id;select.append(option);}
    select.value=selected;
  }
  function prepare(row, projectId='') {
    $('work-project-field').hidden=!!row;fillProjects(projectId);
    $('work').readOnly=!row&&!!projectId;
    if(!row&&projectId)$('work').value=index.projects.find(p=>p.id===projectId)?.name||'';
    $('work-action-message').textContent='';render();
  }
  function render() {
    $('work-trash-open').textContent='Lixeira ('+deleted.size+')';
    if(!$('editor').open)return;
    const row=getRows().find(r=>r.id===getEditing());
    $('work-operations').hidden=!row;
    $('delete-work').hidden=!row; $('delete-record').hidden=!row;
    if(!row)return;
    const project=projectFor(row.id);
    const selected=$('work-record');selected.replaceChildren();
    for(const record of project?.records.filter(r=>!r.deleted&&getRows().some(row=>row.id===r.id))||[]) {const option=make('option',record.reference+' · registro '+record.id);option.value=String(record.id);selected.append(option);}
    selected.value=String(row.id);
    $('work-identity').textContent=(project?'Obra '+project.id.slice(0,8)+' · ':'')+'Romaneio '+row.reference+' · registro '+row.id;
    $('work-shared-note').textContent=project?.records.length>1?'O nome da obra é compartilhado pelos romaneios. Responsável, datas, observações, etiquetas e anexos pertencem ao romaneio e setor selecionados.':'';
    const columns=getColumns().filter(c=>!c.deleted&&!(c.kind==='fixed'&&(['work','actions'].includes(c.key)||(['owner','deadline'].includes(c.key)&&c.type===c.originalType))));
    const area=$('work-operational-cells');area.replaceChildren();
    for(const column of columns) {
      const card=make('section',undefined,'overview-card');card.append(make('h3',columnName(column)));
      card.append(renderCell(column,row,true));area.append(card);
    }
    $('delete-work').disabled=busy||!project; $('delete-record').disabled=busy||!project;
  }
  async function reload(closeEditor=false) {
    if(closeEditor)$('editor').close();
    const state=await persistence.start(); if(state)await attachments.start(state);
    renderTrash();
  }
  async function lifecycle(action) {
    if(busy)return;
    setBusy(true);
    try {
      await persistence.ensureSaved();await refresh();
      const row=getRows().find(r=>r.id===getEditing());const project=row&&projectFor(row.id);
      if(!row||!project)throw new Error('Abra um romaneio ativo para continuar.');
      const count=project.records.filter(r=>!r.deleted).length;
      const text=action==='delete_project'?'Excluir a obra “'+project.name+'” e seus '+count+' romaneio(s) ativos de todos os setores? Os registros e anexos irão para a lixeira.':'Excluir somente o romaneio '+row.reference+' da obra “'+project.name+'”, em todos os setores? Os demais romaneios serão mantidos.';
      if(!confirm(text+(isDirty()?' Os dados básicos ainda não salvos desta janela serão descartados.':'')))return;
      await persistence.request('/api/works',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,revision:index.revision,confirm:true,...(action==='delete_project'?{project_id:project.id}:{record_id:row.id})})});
      await reload(true);notice('Exclusão confirmada. Os registros e anexos podem ser recuperados na lixeira.');
    }catch(error){notice(error.message);}finally{setBusy(false);render();}
  }
  function renderTrash() {
    const area=$('work-trash-list');area.replaceChildren();
    if(!index.batches.length)area.append(make('p','A lixeira está vazia.','muted'));
    for(const batch of index.batches) {
      const card=make('section',undefined,'trash-entry');card.append(make('strong',batch.kind==='delete_project'?'Obra excluída':'Romaneio excluído'));
      card.append(make('p',batch.records.map(r=>r.work+' · '+r.reference+' · registro '+r.id).join(' | ')));
      const restore=make('button','Restaurar','secondary');restore.type='button';restore.disabled=busy;
      restore.addEventListener('click',async()=>{
        if(busy)return;setBusy(true);
        try {
          await persistence.ensureSaved();
          const current=await persistence.request('/api/works');loaded(current);
          const entry=current.batches.find(b=>b.id===batch.id);
          if(!entry)throw new Error('Esta exclusão não está mais na lixeira. Atualize a lista.');
          if(!confirm('Restaurar '+entry.records.length+' romaneio(s), com seus dados e anexos, em todos os setores?'))return;
          await persistence.request('/api/works',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'restore',revision:current.revision,batch_id:batch.id,confirm:true})});
          await reload();notice('Restauração confirmada no computador.');
        }catch(error){notice(error.message);}finally{setBusy(false);renderTrash();render();}
      });card.append(restore);area.append(card);
    }
  }
  $('work-project').addEventListener('change',()=>{const project=index.projects.find(p=>p.id===$('work-project').value);$('work').readOnly=!!project;$('work').value=project?.name||'';});
  $('work-record').addEventListener('change',event=>{
    const id=Number(event.target.value);if(id===getEditing())return;
    if(isDirty()&&!confirm('Descartar os dados básicos ainda não salvos para abrir outro romaneio? Etiquetas e anexos já gravados serão mantidos.')){$('work-record').value=String(getEditing());return;}
    openEditor(getRows().find(r=>r.id===id));
  });
  $('work-new-record').addEventListener('click',()=>{
    const project=projectFor(getEditing());if(!project)return;
    if(isDirty()&&!confirm('Descartar os dados básicos ainda não salvos para adicionar outro romaneio?'))return;
    openEditor(null);prepare(null,project.id);
  });
  $('delete-work').addEventListener('click',()=>lifecycle('delete_project'));
  $('delete-record').addEventListener('click',()=>lifecycle('delete_record'));
  $('work-trash-open').addEventListener('click',async()=>{
    try {await persistence.ensureSaved();await refresh();if(!$('work-trash').open)$('work-trash').showModal();}catch(error){notice(error.message);}
  });
  $('work-trash-close').addEventListener('click',()=>{if(!busy)$('work-trash').close();});
  $('work-trash-refresh').addEventListener('click',async()=>{if(!busy){try{await refresh();}catch(error){notice(error.message);}}});
  $('work-trash').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  $('editor').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  return {loaded,prepare,render,isDeleted:id=>deleted.has(id),
    async boardSaved(state) {
      const known=new Map(index.projects.flatMap(p=>p.records.map(r=>[r.id,[p.name,r.reference]])));
      if(state.rows.some(r=>!known.has(r.id)||known.get(r.id)[0]!==r.work||known.get(r.id)[1]!==r.reference))await refresh();else render();
    },
    async createLinked(fields) {
      const pid=$('work-project').value;if(!pid)return false;
      await persistence.ensureSaved();await refresh();
      const project=index.projects.find(p=>p.id===pid);
      if(!project||!project.records.some(r=>!r.deleted))throw new Error('A obra escolhida não está mais ativa. Atualize a seleção.');
      fields={...fields,work:project.name};
      await persistence.request('/api/works',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'create_record',revision:index.revision,project_id:pid,fields})});
      await reload(true);return true;
    }};
}
