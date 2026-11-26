import {createPersistence} from './persistencia.js';
import {createAttachments} from './anexos.js';
import {createSectors} from './setores.js';
import {createWorkOverview} from './obras.js';
import {createFlow} from './fluxo.js';


(async () => {

'use strict';

const $=id=>document.getElementById(id);
let attachments = null;
let flow=null;
let workOverview = null;
let editorBaseline = null;
let persistence=null;
let workflowVersion=0;
const labelDescriptions={};

const materials=['Perfis','Vidros','Telas','Acessórios'];

const fixedHeaders={work:'Obra / romaneio',owner:'Responsável',deadline:'Prazo',summary:'Status da compra',actions:'Dados'};

const stages=['Não iniciado','Aguardando projeto','Orçar','Revisar orçamento','Aguardando liberação','Aguardando compra','Compra parcial','Comprado','Aguardando entrega','Em pintura','Recebido','Não se aplica'];

const customColors=new Map();

const excluded=new Set(['Não se aplica']);

const summaryStages=['Em andamento','Concluída','Parado','Pendência','Sem itens previstos'];

const summaryColors=new Map([['Em andamento','#e39136'],['Concluída','#3377cc'],['Parado','#cf6681'],['Pendência','#c84b97'],['Sem itens previstos','#e9edf4']]);

const summaryDone=new Set(['Concluída']);

const summaryDefaults={pending:'Em andamento',done:'Concluída',empty:'Sem itens previstos'};

const defaults={notStarted:'Não iniciado',notApplicable:'Não se aplica',approval:'Aguardando liberação'};

const purchased=new Set(['Comprado','Aguardando entrega','Em pintura','Recebido']);

const fields=['work','reference','owner','received','deadline','notes'];

const localDate=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;

const today=()=>localDate(new Date());

const relative=n=>{const d=new Date();d.setDate(d.getDate()+n);return localDate(d);};

const format=s=>s.split('-').reverse().join('/');

const tags=(...values)=>Object.fromEntries(materials.map((material,i)=>[material,values[i]]));

let rows=[

 {id:1,work:'Obra Exemplo Aurora',reference:'ROM-001',owner:'Ana · exemplo',received:relative(-3),deadline:relative(4),notes:'Romaneio fictício recebido de Projetos.',labels:tags('Orçar','Revisar orçamento','Aguardando liberação','Não se aplica')},

 {id:2,work:'Obra Exemplo Horizonte',reference:'ROM-002',owner:'Bruno · exemplo',received:relative(-5),deadline:relative(-1),notes:'Aguardando decisão sobre os perfis.',labels:tags('Aguardando liberação','Aguardando compra','Comprado','Compra parcial')},

 {id:3,work:'Obra Exemplo Jardim',reference:'ROM-003',owner:'Ana · exemplo',received:relative(-2),deadline:relative(6),notes:'',labels:tags('Em pintura','Aguardando projeto','Não se aplica','Não iniciado')},

 {id:4,work:'Obra Exemplo Sol',reference:'ROM-004',owner:'Carla · exemplo',received:relative(-8),deadline:relative(-2),notes:'Compra fictícia já realizada; entrega dos vidros pendente.',labels:tags('Recebido','Aguardando entrega','Não se aplica','Comprado')}

];

let nextId=5,editing=null;

const isComplete=row=>summaryDone.has(summaryValue(row));

const summaryValue=row=>row.summary??summaryDefaults.pending;

const normalize=text=>text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();

function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}

function clearErrors(){fields.forEach(f=>{const error=$('error-'+f);if(error)error.textContent='';$(f).removeAttribute('aria-invalid');});}

function syncEditorFields(){if(!$('editor').open||!editorBaseline||editing===null)return;const row=rows.find(r=>r.id===editing);if(!row)return;fields.forEach(f=>{const value=row[f]??'';if($(f).value===editorBaseline[f])$(f).value=value;editorBaseline[f]=value;});}

function openEditor(row){editing=row?row.id:null;$('form').reset();clearErrors();$('editor-heading').textContent=row?'Editar dados da obra':'Adicionar Obra';$('save').textContent=row?'Salvar dados':'Adicionar ao quadro';if(row)fields.forEach(f=>$(f).value=row[f]??'');else {$('received').value=today();$('owner').value='Não atribuído';}editorBaseline=row?Object.fromEntries(fields.map(f=>[f,row[f]??''])):null;if(!$('editor').open)$('editor').showModal();workOverview?.prepare(row);if(row)flow?.related(row);else $('work-related').replaceChildren();$('work').focus();}

const baseColors=['#e9edf4','#7795ce','#ec9646','#b274a3','#d1ab3e','#5675ce','#bf7e52','#2d9b83','#518fba','#9471b3','#25876f','#e9edf4'];

let labelContext=null;

function configFor(material){return material===null?{stages:summaryStages,colors:summaryColors,purchased:summaryDone,excluded:new Set(),defaults:summaryDefaults}:{stages,colors:customColors,purchased,excluded,defaults};}

function currentLabel(row,material){return material===null?summaryValue(row):row.labels[material];}

function setLabel(row,material,stage){if(material===null)row.summary=stage;else row.labels[material]=stage;}

function colorOf(stage,material){const cfg=configFor(material);return cfg.colors.get(stage)||(material!==null?baseColors[stages.indexOf(stage)]:null)||'#6178b9';}

function paintLabel(element,stage,material){const color=colorOf(stage,material);element.style.backgroundColor=color;const rgb=color.slice(1).match(/../g).map(n=>parseInt(n,16));element.style.color=rgb[0]*.299+rgb[1]*.587+rgb[2]*.114>165?'#24344b':'#fff';}

function labelAnchor(){return labelContext?[...document.querySelectorAll('button.tag')].find(b=>Boolean(b.dataset.overview)===Boolean(labelContext.overview)&&b.dataset.row===String(labelContext.rowId)&&(labelContext.material===null?b.dataset.kind==='summary':b.dataset.kind==='material'&&b.dataset.material===labelContext.material)):null;}

function closeLabelMenu(focus=true){const anchor=labelAnchor();$('label-popover').hidden=true;$('label-popover').replaceChildren();if(anchor){anchor.setAttribute('aria-expanded','false');if(focus)anchor.focus();}labelContext=null;}

function positionLabelMenu(){const anchor=labelAnchor();if(!anchor){closeLabelMenu(false);return;}const pop=$('label-popover'),rect=anchor.getBoundingClientRect();pop.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-pop.offsetWidth-8))+'px';let top=rect.bottom+8;if(top+pop.offsetHeight>window.innerHeight-8)top=rect.top-pop.offsetHeight-8;pop.style.top=Math.max(8,Math.min(top,window.innerHeight-pop.offsetHeight-8))+'px';}

function returnToLabel(context){labelContext=context;const anchor=labelAnchor();labelContext=null;if(anchor)anchor.focus();}

function openLabelMenu(anchor,rowId,material){closeColumnMenu(false);closeLabelMenu(false);labelContext={rowId,material,overview:!!anchor.dataset.overview};const popup=$('label-popover');(labelContext.overview?$('editor'):document.body).append(popup);anchor.setAttribute('aria-expanded','true');const row=rows.find(r=>r.id===rowId),pop=$('label-popover'),cfg=configFor(material);pop.hidden=false;pop.replaceChildren(node('div',(material===null?fixedHeaders.summary:materialCaption(material))+' · '+row.reference,'label-caption'));const list=node('div',undefined,'label-list');list.setAttribute('role','group');list.setAttribute('aria-label','Escolher etapa');cfg.stages.forEach(stage=>{const option=node('button',undefined,'label-option');option.append(node('strong',stage),node('small',labelDescriptions[stage]||'Etiqueta personalizada deste setor.'));option.title=labelDescriptions[stage]||'Etiqueta personalizada deste setor.';option.type='button';option.setAttribute('aria-pressed',String(currentLabel(row,material)===stage));paintLabel(option,stage,material);option.addEventListener('click',()=>{const context={...labelContext};setLabel(row,material,stage);closeLabelMenu(false);render();$('message').textContent=(material===null?fixedHeaders.summary:materialCaption(material))+' de '+row.reference+': '+stage+'. Alteração preparada; nenhum pedido emitido ou gasto liberado.';returnToLabel(context);});list.append(option);});pop.append(list);const tools=node('div',undefined,'label-tools');const edit=node('button','✎ Editar etiquetas');edit.type='button';edit.addEventListener('click',()=>openLabelEditor(currentLabel(row,material)));const add=node('button','+ Nova etiqueta');add.type='button';add.addEventListener('click',()=>openLabelEditor(null));tools.append(edit,add);pop.append(tools);positionLabelMenu();(list.querySelector('[aria-pressed=true]')||list.querySelector('button')).focus({preventScroll:true});}

function refreshStageFilter(previous){$('stage-filter').replaceChildren();const any=node('option','Todas as etapas');any.value='';$('stage-filter').append(any);stages.forEach(stage=>{const option=node('option',stage);option.value=stage;$('stage-filter').append(option);});$('stage-filter').value=stages.includes(previous)?previous:'';}

function openLabelEditor(oldName){const material=labelContext.material,cfg=configFor(material),pop=$('label-popover');pop.replaceChildren(node('h3',oldName?'Editar etiqueta':'Nova etiqueta'));pop.append(node('p',oldName?'Nome e cor mudarão em todas as ocorrências desta etiqueta '+(material===null?'na coluna Status da compra.':'nas colunas de materiais deste quadro.'):'Crie uma etiqueta e use nesta célula.','label-caption'));const form=node('form');form.noValidate=true;

 const makeField=(labelText,id,input)=>{const field=node('div',undefined,'field'),label=node('label',labelText);label.htmlFor=id;input.id=id;field.append(label,input);form.append(field);return input;};

 const name=makeField('Nome da etiqueta','inline-label-name',node('input'));name.maxLength=35;name.value=oldName||'';name.required=true;

 const description=makeField('Quando utilizar','inline-label-description',node('input'));description.maxLength=300;description.value=labelDescriptions[oldName]||'';
 const color=makeField('Cor da etiqueta','inline-label-color',node('input'));color.type='color';color.value=oldName?colorOf(oldName,material):'#6178b9';

 const meaning=makeField('Significado no resumo','inline-label-meaning',node('select'));const meanings=[['pending','Compra ainda pendente'],['purchased','Compra já realizada']];if(material!==null)meanings.push(['excluded','Material não previsto']);meanings.forEach(([value,text])=>{const option=node('option',text);option.value=value;meaning.append(option);});meaning.value=oldName&&cfg.excluded.has(oldName)?'excluded':oldName&&cfg.purchased.has(oldName)?'purchased':'pending';

 const error=node('span',undefined,'error');error.id='inline-label-error';error.setAttribute('role','alert');name.setAttribute('aria-describedby',error.id);form.append(error);const actions=node('div',undefined,'dialogactions');const cancel=node('button','Voltar','secondary');cancel.type='button';cancel.addEventListener('click',()=>{const context={...labelContext};const anchor=labelAnchor();if(anchor)openLabelMenu(anchor,context.rowId,context.material);else closeLabelMenu();});const save=node('button',oldName?'Salvar etiqueta':'Criar e usar','primary');save.type='submit';actions.append(cancel,save);form.append(actions);pop.append(form);positionLabelMenu();name.focus();

 form.addEventListener('submit',event=>{event.preventDefault();const newName=name.value.trim();error.textContent='';name.removeAttribute('aria-invalid');if(!newName||cfg.stages.some(stage=>stage!==oldName&&normalize(stage)===normalize(newName))){error.textContent=!newName?'Informe o nome da etiqueta.':'Já existe uma etiqueta com esse nome.';name.setAttribute('aria-invalid','true');name.focus();return;}const context={...labelContext},filter=$('stage-filter').value;

  if(oldName!==null){cfg.stages[cfg.stages.indexOf(oldName)]=newName;rows.forEach(row=>{if(material===null){if(row.summary===oldName)row.summary=newName;}else materials.forEach(m=>{if(row.labels[m]===oldName)row.labels[m]=newName;});});Object.keys(cfg.defaults).forEach(key=>{if(cfg.defaults[key]===oldName)cfg.defaults[key]=newName;});cfg.colors.delete(oldName);cfg.purchased.delete(oldName);cfg.excluded.delete(oldName);}else{cfg.stages.push(newName);setLabel(rows.find(r=>r.id===context.rowId),material,newName);}

  if(oldName&&oldName!==newName)delete labelDescriptions[oldName];labelDescriptions[newName]=description.value.trim();cfg.colors.set(newName,color.value);if(meaning.value==='purchased')cfg.purchased.add(newName);if(meaning.value==='excluded')cfg.excluded.add(newName);if(material!==null)refreshStageFilter(filter===oldName?newName:filter);closeLabelMenu(false);render();$('message').textContent='Etiqueta '+newName+' '+(oldName?'atualizada.':'criada e usada nesta célula.')+' Alteração preparada; nenhum gasto foi liberado.';returnToLabel(context);

 });

}

$('label-popover').addEventListener('click',event=>event.stopPropagation());

document.addEventListener('click',event=>{if(!$('label-popover').hidden&&!$('label-popover').contains(event.target)&&!event.target.closest('button.tag'))closeLabelMenu(false);});

document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('label-popover').hidden){event.preventDefault();closeLabelMenu();}});

window.addEventListener('resize',()=>{if(!$('label-popover').hidden)positionLabelMenu();});

document.addEventListener('scroll',event=>{if(!$('label-popover').hidden&&!$('label-popover').contains(event.target))closeLabelMenu(false);},true);

const columnTypes=[['status','Status + Anexos','▣'],['attachments','Somente Anexos','📎'],['text','Texto','T'],['people','Pessoas','♙'],['timeline','Cronograma','↔'],['date','Data','▦'],['dependency','Dependência','↗'],['number','Números','#']];

let columnSequence=1;

const viewColumns=[...['work','owner','deadline','summary'].map(key=>({id:'fixed-'+key,kind:'fixed',key,type:{work:'text',owner:'people',deadline:'date',summary:'status'}[key],originalType:{work:'text',owner:'people',deadline:'date',summary:'status'}[key]})),...materials.map(key=>({id:'material-'+columnSequence++,kind:'material',key,type:'status',originalType:'status'})),{id:'fixed-actions',kind:'fixed',key:'actions',type:'action',originalType:'action'}];

const typeValues=new Map(),deletedColumns=[];

let columnContext=null;

function keepWorkFirst(){const index=viewColumns.findIndex(c=>c.id==='fixed-work');if(index>0)viewColumns.unshift(viewColumns.splice(index,1)[0]);}

function visibleColumns(){return viewColumns.filter(c=>!c.deleted);}

function visibleStatusMaterials(){return visibleColumns().filter(c=>c.type==='status'&&!(c.kind==='fixed'&&c.key==='summary')).map(c=>c.key);}

function columnName(c){return c.kind==='fixed'?fixedHeaders[c.key]:c.key;}

function materialCaption(key){const c=visibleColumns().find(c=>c.type==='status'&&c.key===key);return c?columnName(c):key;}

function columnById(id){return viewColumns.find(c=>c.id===id);}

function typeName(type){return columnTypes.find(t=>t[0]===type)?.[1]||'Ações';}

function columnAnchor(){return columnContext?[...document.querySelectorAll('.column-head,.column-plus')].find(b=>b.dataset.group===columnContext.group&&b.dataset.column===columnContext.id):null;}

function closeColumnMenu(focus=true){const anchor=columnAnchor();$('column-popover').hidden=true;$('column-popover').replaceChildren();if(anchor){anchor.setAttribute('aria-expanded','false');if(focus)anchor.focus();}columnContext=null;}

function positionColumnMenu(){const anchor=columnAnchor();if(!anchor){closeColumnMenu(false);return;}const pop=$('column-popover'),rect=anchor.getBoundingClientRect();pop.style.left=Math.max(8,Math.min(rect.left,innerWidth-pop.offsetWidth-8))+'px';pop.style.top=Math.max(8,Math.min(rect.bottom+8,innerHeight-pop.offsetHeight-8))+'px';}

function refreshMaterialFilter(previous){$('material-filter').replaceChildren();const all=node('option','Todos os materiais');all.value='';$('material-filter').append(all);const names=visibleStatusMaterials();names.forEach(name=>{const option=node('option',materialCaption(name));option.value=name;$('material-filter').append(option);});$('material-filter').value=names.includes(previous)?previous:'';}

function columnError(name,id=null){if(!name)return 'Informe o nome da coluna.';if(viewColumns.some(c=>c.id!==id&&normalize(columnName(c))===normalize(name)))return 'Já existe uma coluna com esse nome, inclusive entre as excluídas. Renomeie ou desfaça a exclusão.';return '';}

function ensureStatusData(c){if(c.kind==='fixed'&&c.key==='summary')return;const name=c.key;if(!materials.includes(name))materials.push(name);rows.forEach(row=>{if(!Object.hasOwn(row.labels,name))Object.defineProperty(row.labels,name,{value:defaults.notApplicable,writable:true,enumerable:true,configurable:true});});}

function createColumn(name,type='status',anchorId=null,side='right'){const c={id:'custom-'+columnSequence++,kind:'extra',key:name,type,originalType:type};let index=anchorId?viewColumns.findIndex(v=>v.id===anchorId):viewColumns.length;if(index<0)index=viewColumns.length;else if(anchorId&&side==='right')index++;viewColumns.splice(index,0,c);keepWorkFirst();if(type==='status')ensureStatusData(c);refreshMaterialFilter($('material-filter').value);return c;}

function createMaterialColumn(name){return createColumn(name);}

function restoreColumnFocus(context){columnContext=context;const anchor=columnAnchor();columnContext=null;if(anchor)anchor.focus();}

function finishColumn(message,context){closeColumnMenu(false);refreshMaterialFilter($('material-filter').value);render();$('message').textContent=message;restoreColumnFocus(context);}

function menuButton(container,text,action,danger=false){const button=node('button',text);button.type='button';if(danger)button.className='danger-action';button.addEventListener('click',action);container.append(button);return button;}

function openColumnMenu(anchor,id,group){closeLabelMenu(false);closeColumnMenu(false);columnContext={id,group};anchor.setAttribute('aria-expanded','true');const c=columnById(id),pop=$('column-popover');pop.hidden=false;pop.replaceChildren(node('h3',columnName(c)),node('p','Tipo: '+typeName(c.type),'label-caption'));const tools=node('div',undefined,'label-tools');const first=menuButton(tools,'Renomear',()=>openColumnEditor('rename'));menuButton(tools,'Adicionar coluna à esquerda',()=>openTypePicker('left'));menuButton(tools,'Adicionar coluna à direita',()=>openTypePicker('right'));const changeType=menuButton(tools,'Alterar tipo de coluna',()=>openTypePicker('change'));const remove=menuButton(tools,'Excluir',openDeleteColumn,true);if(c.role==='project_code'){changeType.disabled=true;changeType.title='O código central permanece como Texto.';}if(c.id==='fixed-work'){changeType.disabled=true;remove.disabled=true;changeType.title=remove.title='O nome da obra permanece visível e do tipo Texto.';}pop.append(tools);positionColumnMenu();first.focus({preventScroll:true});}

function openNewColumn(anchor,group){closeLabelMenu(false);closeColumnMenu(false);columnContext={id:'',group};anchor.setAttribute('aria-expanded','true');$('column-popover').hidden=false;openTypePicker('right');}

function openTypePicker(mode){const pop=$('column-popover');pop.replaceChildren(node('h3',mode==='change'?'Alterar tipo de coluna':'Escolha o tipo da nova coluna'));const tools=node('div',undefined,'label-tools column-type-list');columnTypes.forEach(([type,label,icon])=>menuButton(tools,icon+'  '+label,()=>{if(mode==='change')confirmColumnType(type);else openColumnEditor('add',type,mode);}));if(mode==='change'){const c=columnById(columnContext.id);if(c.type!==c.originalType)menuButton(tools,'Restaurar tipo original',()=>confirmColumnType(c.originalType));}menuButton(tools,'Cancelar',()=>closeColumnMenu());pop.append(tools);positionColumnMenu();tools.querySelector('button').focus({preventScroll:true});}

function confirmColumnType(type){const c=columnById(columnContext.id);if(c.id==='fixed-work'||c.role==='project_code')return;const pop=$('column-popover');pop.replaceChildren(node('h3','Alterar para '+typeName(type)),node('p','Os valores do tipo anterior serão preservados no computador. Ao voltar ao tipo anterior, eles reaparecem. Cada tipo mantém seus próprios valores.','label-caption'));if(c.type==='status'&&!(c.kind==='fixed'&&c.key==='summary'))pop.append(node('p','Ao sair de Status, esta coluna deixa de participar dos filtros de materiais. Seus arquivos ficam preservados.','label-caption'));const tools=node('div',undefined,'label-tools');menuButton(tools,'Confirmar alteração de tipo',()=>{const context={...columnContext};c.type=type;if(type==='status')ensureStatusData(c);finishColumn('Tipo de '+columnName(c)+' alterado para '+typeName(type)+'. Valores anteriores preservados no computador.',context);});menuButton(tools,'Cancelar',()=>closeColumnMenu());pop.append(tools);positionColumnMenu();}

function openDeleteColumn(){const c=columnById(columnContext.id);if(c.id==='fixed-work'||c.role==='project_code')return;const pop=$('column-popover');pop.replaceChildren(node('h3','Excluir '+columnName(c)+'?'),node('p','A coluna sairá dos dois quadros. Seus dados ficam preservados no computador e você poderá usar Desfazer exclusão. Nenhuma obra será excluída.','label-caption'));const tools=node('div',undefined,'label-tools');menuButton(tools,'Excluir coluna',()=>{c.deleted=true;deletedColumns.push(c.id);closeColumnMenu(false);refreshMaterialFilter($('material-filter').value);render();$('message').textContent='Coluna '+columnName(c)+' excluída do quadro. Use Desfazer exclusão para recuperar seus dados.';},true);menuButton(tools,'Cancelar',()=>closeColumnMenu());pop.append(tools);positionColumnMenu();}

function openColumnEditor(mode,type='status',side='right'){const context={...columnContext},current=columnById(context.id),previous=mode==='rename'?columnName(current):null,pop=$('column-popover');pop.replaceChildren(node('h3',mode==='rename'?'Renomear coluna':'Adicionar coluna '+(side==='left'?'à esquerda':'à direita')),node('p',mode==='rename'?'O título mudará nos dois quadros. Os valores preenchidos serão mantidos.':'Tipo: '+typeName(type)+'. A coluna terá valores próprios para cada obra.','label-caption'));const form=node('form');form.noValidate=true;const field=node('div',undefined,'field'),label=node('label','Nome da coluna'),input=node('input');input.id='inline-column-name';label.htmlFor=input.id;input.maxLength=30;input.required=true;input.value=previous||'';input.setAttribute('aria-describedby','inline-column-error');field.append(label,input);form.append(field);const error=node('span',undefined,'error');error.id='inline-column-error';error.setAttribute('role','alert');form.append(error);const actions=node('div',undefined,'dialogactions'),cancel=node('button','Cancelar','secondary'),save=node('button',mode==='rename'?'Salvar nome':'Criar coluna','primary');cancel.type='button';cancel.addEventListener('click',()=>closeColumnMenu());save.type='submit';actions.append(cancel,save);form.append(actions);pop.append(form);positionColumnMenu();input.focus();

 form.addEventListener('submit',event=>{event.preventDefault();const name=input.value.trim(),message=columnError(name,mode==='rename'?current.id:null);error.textContent=message;input.removeAttribute('aria-invalid');if(message){input.setAttribute('aria-invalid','true');input.focus();return;}let target=current;const filter=$('material-filter').value;

  if(mode==='add')target=createColumn(name,type,context.id||null,side);

  else if(current.kind==='fixed')fixedHeaders[current.key]=name;

  else if(name!==previous){if(materials.includes(previous)){const index=materials.indexOf(previous);rows.forEach(row=>{if(Object.hasOwn(row.labels,previous)){Object.defineProperty(row.labels,name,{value:row.labels[previous],writable:true,enumerable:true,configurable:true});delete row.labels[previous];}});materials[index]=name;}current.key=name;refreshMaterialFilter(filter===previous?name:filter);}

  finishColumn(mode==='add'?'Coluna '+name+' criada como '+typeName(type)+'.':'Coluna renomeada para '+name+'. Valores mantidos.',{id:target.id,group:context.group});

 });

}

$('undo-column').addEventListener('click',()=>{const id=deletedColumns.pop();if(!id)return;const c=columnById(id);c.deleted=false;refreshMaterialFilter($('material-filter').value);render();$('message').textContent='Coluna '+columnName(c)+' restaurada com seus valores e posição.';});

$('column-popover').addEventListener('click',event=>event.stopPropagation());

document.addEventListener('click',event=>{if(!$('column-popover').hidden&&!$('column-popover').contains(event.target)&&!event.target.closest('.column-head,.column-plus'))closeColumnMenu(false);});

document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('column-popover').hidden){event.preventDefault();closeColumnMenu();}});

window.addEventListener('resize',()=>{if(!$('column-popover').hidden)positionColumnMenu();});

document.addEventListener('scroll',event=>{if(!$('column-popover').hidden&&!$('column-popover').contains(event.target))closeColumnMenu(false);},true);

function columnWidth(c){return c.kind==='fixed'&&c.key==='work'?240:c.type==='timeline'?200:c.type==='dependency'?185:c.type==='text'?160:c.type==='action'?70:140;}

let columnDrag=null,ignoreHeaderClickUntil=0;

function clearColumnDrag(){document.querySelectorAll('.drop-before,.drop-after,.column-dragging').forEach(el=>el.classList.remove('drop-before','drop-after','column-dragging'));columnDrag=null;}

function moveColumn(sourceId,targetId,after,group){const source=columnById(sourceId),target=columnById(targetId);if(!source||!target||source.deleted||target.deleted||sourceId==='fixed-work'||sourceId===targetId)return false;const previous=viewColumns.map(c=>c.id).join('|');if(targetId==='fixed-work')after=true;const from=viewColumns.findIndex(c=>c.id===sourceId);viewColumns.splice(from,1);const to=viewColumns.findIndex(c=>c.id===targetId);viewColumns.splice(to+(after?1:0),0,source);keepWorkFirst();if(previous===viewColumns.map(c=>c.id).join('|'))return false;closeLabelMenu(false);closeColumnMenu(false);render();$('message').textContent='Coluna '+columnName(source)+' movida. A ordem foi atualizada nos dois quadros; o nome da obra continua fixo. Aguarde a confirmação de gravação.';const button=[...document.querySelectorAll('.column-head')].find(b=>b.dataset.column===sourceId&&b.dataset.group===group);if(button)button.focus({preventScroll:true});return true;}

let pointerColumn=null;

function pointerColumnTarget(x,y){const element=document.elementFromPoint(x,y),th=element?.closest('th'),button=th?.querySelector('.column-head');if(!button)return null;const c=columnById(button.dataset.column);if(!c||c.deleted)return null;const rect=th.getBoundingClientRect();return {id:c.id,after:c.id==='fixed-work'||x>rect.left+rect.width/2,th};}

function finishPointerDrag(commit,event=null){const context=pointerColumn;if(!context)return;pointerColumn=null;const target=event?pointerColumnTarget(event.clientX,event.clientY):null;try{if(context.button.hasPointerCapture(context.pointerId))context.button.releasePointerCapture(context.pointerId);}catch(_){}if(context.active)ignoreHeaderClickUntil=Date.now()+350;clearColumnDrag();document.body.classList.remove('dragging-columns');if(commit&&context.active&&target)moveColumn(context.id,target.id,target.after,context.group);}

function bindColumnDrag(th,button,c,group){const pinned=c.id==='fixed-work';button.draggable=false;

 if(pinned){button.title='Nome da obra fixo à esquerda';button.prepend(node('span','▣','pinned-icon'));return;}

 button.title='Arraste pela alça ⠿ para reorganizar; clique no título para abrir o menu. Alt + setas também move a coluna.';button.setAttribute('aria-keyshortcuts','Alt+ArrowLeft Alt+ArrowRight');const grip=node('span','⠿','drag-grip');grip.draggable=false;grip.setAttribute('aria-hidden','true');grip.title='Arrastar coluna';button.prepend(grip);

 button.addEventListener('pointerdown',event=>{if(event.button!==0||!event.isPrimary)return;pointerColumn={id:c.id,group,button,th,x:event.clientX,y:event.clientY,pointerId:event.pointerId,active:false};button.setPointerCapture(event.pointerId);});

 button.addEventListener('keydown',event=>{if(!event.altKey||!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();const columns=visibleColumns(),index=columns.findIndex(v=>v.id===c.id),next=columns[index+(event.key==='ArrowLeft'?-1:1)];if(next)moveColumn(c.id,next.id,event.key==='ArrowRight',group);});

}

document.addEventListener('pointermove',event=>{const context=pointerColumn;if(!context||event.pointerId!==context.pointerId)return;if(!context.active){if(Math.hypot(event.clientX-context.x,event.clientY-context.y)<7)return;context.active=true;columnDrag={id:context.id,group:context.group};closeLabelMenu(false);closeColumnMenu(false);context.th.classList.add('column-dragging');document.body.classList.add('dragging-columns');}event.preventDefault();document.querySelectorAll('.drop-before,.drop-after').forEach(el=>el.classList.remove('drop-before','drop-after'));const target=pointerColumnTarget(event.clientX,event.clientY);if(target&&target.id!==context.id)target.th.classList.add(target.after?'drop-after':'drop-before');},{passive:false});

document.addEventListener('pointerup',event=>{if(pointerColumn&&event.pointerId===pointerColumn.pointerId)finishPointerDrag(true,event);});

document.addEventListener('pointercancel',()=>finishPointerDrag(false));

document.addEventListener('keydown',event=>{if(event.key==='Escape'&&pointerColumn){ignoreHeaderClickUntil=Date.now()+350;finishPointerDrag(false);}});

function renderHeaders(){document.querySelectorAll('thead tr').forEach((tr,index)=>{tr.replaceChildren();const group=index===0?'em andamento':'concluídas';visibleColumns().forEach(c=>{const th=node('th');if(c.id==='fixed-work')th.classList.add('pinned-work');th.scope='col';th.style.width=columnWidth(c)+'px';const button=node('button',undefined,'column-head');button.type='button';button.dataset.group=group;button.dataset.column=c.id;button.setAttribute('aria-label','Coluna '+columnName(c)+' — '+group);button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');button.append(node('span',columnTypes.find(t=>t[0]===c.type)?.[2]||'⋯','type-icon'),node('span',columnName(c)),node('span','⌄','column-arrow'));button.addEventListener('click',()=>{if(Date.now()<ignoreHeaderClickUntil)return;openColumnMenu(button,c.id,group);});bindColumnDrag(th,button,c,group);th.append(button);tr.append(th);});const th=node('th');th.style.width='42px';const add=node('button','+','column-plus');add.type='button';add.dataset.group=group;add.dataset.column='';add.setAttribute('aria-label','Adicionar coluna — '+group);add.setAttribute('aria-haspopup','dialog');add.setAttribute('aria-expanded','false');add.addEventListener('click',()=>openNewColumn(add,group));th.append(add);tr.append(th);});document.querySelectorAll('table').forEach(t=>t.style.minWidth=(visibleColumns().reduce((n,c)=>n+columnWidth(c),0)+42)+'px');}

function storedValue(c,row){if(c.role==='project_code')return row.projectCode||'';if(c.kind==='fixed'&&c.type===c.originalType){if(c.key==='work')return row.work;if(c.key==='owner')return row.owner;if(c.key==='deadline')return row.deadline;}return typeValues.get(c.id)?.get(row.id)?.get(c.type)??'';}

function saveStoredValue(c,row,value){if(c.role==='project_code'){row.projectCode=value;return;}if(c.kind==='fixed'&&c.type===c.originalType&&['work','owner','deadline'].includes(c.key)){if(c.key==='deadline')delete row.deadlineRule;row[{work:'work',owner:'owner',deadline:'deadline'}[c.key]]=value;return;}if(!typeValues.has(c.id))typeValues.set(c.id,new Map());const byRow=typeValues.get(c.id);if(!byRow.has(row.id))byRow.set(row.id,new Map());byRow.get(row.id).set(c.type,value);}

function wouldCycle(source,target,column){const seen=new Set();function walk(id){if(id===source)return true;if(seen.has(id))return false;seen.add(id);return visibleColumns().filter(c=>c.type==='dependency').some(c=>{const r=rows.find(r=>r.id===id);if(!r)return false;const next=c.id===column.id&&id===source?target:storedValue(c,r);return next!==''&&walk(Number(next));});}return walk(target);}

function openCellEditor(c,row){closeColumnMenu(false);closeLabelMenu(false);const area=$('cell-content');area.replaceChildren();$('cell-title').textContent=columnName(c)+' · '+row.reference;const form=node('form');form.noValidate=true;const value=storedValue(c,row),inputs={};

 const addField=(caption,key,type,initial)=>{const field=node('div',undefined,'field'),label=node('label',caption),input=node('input');input.id='cell-'+key;input.type=type;input.value=initial??'';if(type==='text')input.maxLength=1000;if(type==='number')input.step='any';label.htmlFor=input.id;field.append(label,input);form.append(field);inputs[key]=input;return input;};

 if(c.type==='timeline'){addField('Início do cronograma','start','date',value.start||'');addField('Fim do cronograma','end','date',value.end||'');}

 else if(c.type==='dependency'){const field=node('div',undefined,'field'),label=node('label','Depende da obra'),select=node('select');select.id='cell-dependency';label.htmlFor=select.id;const none=node('option','Sem dependência');none.value='';select.append(none);rows.filter(r=>r.id!==row.id&&(!workOverview?.isDeleted(r.id)||String(r.id)===String(value))).forEach(r=>{const option=node('option',r.reference+' · '+r.work+(workOverview?.isDeleted(r.id)?' (na lixeira)':''));option.value=String(r.id);select.append(option);});select.value=String(value);field.append(label,select);form.append(field,node('p','Vínculo de acompanhamento. Não recalcula datas nem bloqueia etapas automaticamente.','label-caption'));inputs.value=select;}

 else{addField(c.type==='people'?'Pessoas (nomes separados por vírgula)':c.type==='number'?'Valor numérico':c.type==='date'?'Data':'Texto','value',c.type==='number'?'number':c.type==='date'?'date':'text',value);if(c.type==='people')form.append(node('p','Nomes digitados para a demonstração; não são contas, permissões ou notificações.','label-caption'));}

 const error=node('span',undefined,'error');error.id='cell-error';error.setAttribute('role','alert');form.append(error);const actions=node('div',undefined,'dialogactions'),cancel=node('button','Cancelar','secondary'),save=node('button','Salvar valor','primary');cancel.type='button';cancel.addEventListener('click',()=>$('cell-editor').close());save.type='submit';actions.append(cancel,save);form.append(actions);area.append(form);$('cell-editor').showModal();Object.values(inputs)[0].focus();

 form.addEventListener('submit',event=>{event.preventDefault();error.textContent='';let next;

  if(c.type==='timeline'){const start=inputs.start.value,end=inputs.end.value;if((start||end)&&(!validDate(start)||!validDate(end)||end<start)){error.textContent='Informe início e fim válidos, com fim igual ou posterior ao início.';return;}next=start?{start,end}:'';}

  else{next=inputs.value.value.trim();if(c.type==='date'&&next&&!validDate(next)){error.textContent='Informe uma data válida.';return;}if(c.type==='number'&&(inputs.value.validity.badInput||next!==''&&!Number.isFinite(Number(next)))){error.textContent='Informe um número válido.';return;}if(c.type==='number'&&next!=='')next=Number(next);if(c.type==='dependency'&&next!==''&&(!rows.some(r=>r.id===Number(next))||Number(next)===row.id||wouldCycle(row.id,Number(next),c))){error.textContent='Essa dependência criaria um ciclo. Escolha outra obra.';return;}if(c.kind==='fixed'&&c.type===c.originalType&&['work','owner','deadline'].includes(c.key)&&next===''){error.textContent='Este campo da obra é obrigatório.';return;}if(c.kind==='fixed'&&c.key==='deadline'&&c.type==='date'&&next<row.received){error.textContent='O prazo deve ser igual ou posterior ao recebimento.';return;}}

  if(c.role==='project_code'&&(!String(next).trim()||String(next).length>50)){error.textContent='Informe um código com até 50 caracteres.';return;}saveStoredValue(c,row,next);$('cell-editor').close();render();$('message').textContent='Valor de '+columnName(c)+' salvo no quadro. Aguarde a confirmação de gravação.';

 });

}

$('cell-close').addEventListener('click',()=>$('cell-editor').close());

function renderCell(c,row,overview=false){const cell=node(overview?'div':'td');if(c.type==='attachments'){attachments?.decorate(cell,c.id,row.id,columnName(c)+' · '+row.reference,overview);return cell;}if(c.type==='status'){const material=c.kind==='fixed'&&c.key==='summary'?null:c.key;const button=node('button',currentLabel(row,material),'tag');button.title=labelDescriptions[currentLabel(row,material)]||'Etiqueta personalizada deste setor.';button.type='button';button.dataset.row=String(row.id);if(overview)button.dataset.overview='true';button.dataset.kind=material===null?'summary':'material';if(material!==null)button.dataset.material=material;button.setAttribute('aria-label',columnName(c)+' — '+row.reference+': '+currentLabel(row,material));button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');paintLabel(button,currentLabel(row,material),material);button.addEventListener('click',()=>openLabelMenu(button,row.id,material));cell.className='labelcell';cell.append(button);if(material!==null) if(c.kind!=='fixed')attachments?.decorate(cell,c.id,row.id,columnName(c)+' · '+row.reference,overview);return cell;}

 if(c.type==='action'){const edit=node('button','Editar','edit');edit.type='button';edit.setAttribute('aria-label','Editar dados — '+row.reference);edit.addEventListener('click',()=>openEditor(row));cell.append(edit);if(flow){const forward=node('button','Encaminhar','edit');forward.type='button';forward.addEventListener('click',()=>flow.openForward(row).catch(e=>{$('message').textContent=e.message;}));cell.append(forward);const plan=node('button','Configurar prazo','edit');plan.type='button';plan.addEventListener('click',()=>flow.configureDeadline(row).catch(e=>{$('message').textContent=e.message;}));cell.append(plan);}return cell;}

 const value=storedValue(c,row);let text=value;if(c.type==='date'&&value)text=format(value);if(c.type==='timeline'&&value)text=format(value.start)+' → '+format(value.end);if(c.type==='dependency'&&value){const target=rows.find(r=>r.id===Number(value));text=target?target.reference+' · '+target.work:'Obra não encontrada';}if(c.type==='number'&&value!=='')text=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:10}).format(value);const button=node('button',text===''?'Adicionar…':String(text),'cell-edit'+(text===''?' empty':''));button.type='button';button.dataset.row=String(row.id);button.dataset.column=c.id;button.setAttribute('aria-label','Editar '+columnName(c)+' — '+row.reference);button.addEventListener('click',()=>openCellEditor(c,row));cell.append(button);if(c.kind==='fixed'&&c.key==='work')cell.append(node('span',(row.projectCode||row.reference)+' · início em '+format(row.received),'sub'));if(c.kind==='fixed'&&c.key==='deadline'&&c.type==='date'){const days=Math.round((new Date(row.deadline+'T12:00:00')-new Date(today()+'T12:00:00'))/86400000);cell.append(node('span',isComplete(row)?'Contagem encerrada':days<0?Math.abs(days)+' dia(s) de atraso':days+' dia(s) restantes',!isComplete(row)&&days<0?'late':'sub'));}return cell;}

function render(){

 const activeRows=rows.filter(r=>!r.archived&&!workOverview?.isDeleted(r.id));
 renderHeaders();

 const legend=document.querySelector('.legend');legend.replaceChildren();stages.slice(2,8).forEach(stage=>{const chip=node('span',stage);paintLabel(chip,stage,'');legend.append(chip);});

 $('total').textContent=activeRows.length;$('pending').textContent=activeRows.filter(r=>!isComplete(r)).length;$('completed').textContent=activeRows.filter(isComplete).length;

 $('approval').textContent=activeRows.reduce((count,row)=>count+visibleStatusMaterials().filter(m=>row.labels[m]===defaults.approval).length,0);

 const query=normalize($('search').value.trim()),material=$('material-filter').value,stage=$('stage-filter').value;

 const visible=activeRows.filter(row=>(!query||normalize(`${row.work} ${row.reference} ${row.owner}`).includes(query))&&(!stage||(material?row.labels[material]===stage:visibleStatusMaterials().some(m=>row.labels[m]===stage))));

 $('pending-rows').replaceChildren();$('done-rows').replaceChildren();

 visible.forEach(row=>{const tr=node('tr');visibleColumns().forEach(c=>{const cell=renderCell(c,row);if(c.id==='fixed-work')cell.classList.add('pinned-work');tr.append(cell);});tr.append(node('td'));$(isComplete(row)?'done-rows':'pending-rows').append(tr);});

 $('undo-column').hidden=deletedColumns.length===0;

 const pending=visible.filter(r=>!isComplete(r)).length,done=visible.length-pending;

 $('pending-visible').textContent=pending+' romaneio(s)';$('done-visible').textContent=done+' romaneio(s)';$('pending-empty').hidden=pending>0;$('done-empty').hidden=done>0;
 syncEditorFields();
 workOverview?.render();
 persistence?.notify();

}

function validDate(value){if(!/^\d{4}-\d{2}-\d{2}$/.test(value)||value.startsWith('0000'))return false;const d=new Date(value+'T12:00:00');return !Number.isNaN(d.getTime())&&localDate(d)===value;}

$('stage-filter').append(node('option','Todas as etapas'));$('stage-filter').firstElementChild.value='';stages.forEach(stage=>{const option=node('option',stage);option.value=stage;$('stage-filter').append(option);});

$('editor').addEventListener('close',()=>{if(labelContext?.overview)closeLabelMenu(false);document.body.append($('label-popover'));});
$('editor').addEventListener('cancel',event=>{if($('editor').dataset.saving)event.preventDefault();});
$('new').addEventListener('click',()=>openEditor(null));['close','cancel'].forEach(id=>$(id).addEventListener('click',()=>$('editor').close()));

$('form').addEventListener('submit',async event=>{
 event.preventDefault();if($('editor').dataset.saving)return;
 $('editor').dataset.saving='true';$('editor').inert=true;
 try {
  // Primeiro drena alterações anteriores e atualiza os campos ainda não editados.
  await persistence.ensureSaved();syncEditorFields();clearErrors();
  const values=Object.fromEntries(fields.map(f=>[f,$(f).value.trim()])),errors={};
  if(!values.work)errors.work='Informe a obra ou cliente.';
  if(!values.reference)errors.reference='Informe o número do romaneio.';
  if(!values.owner)errors.owner='Informe o responsável.';
  if(values.reference&&rows.some(r=>r.id!==editing&&normalize(r.reference)===normalize(values.reference)))errors.reference='Esse número de romaneio já existe, inclusive na lixeira. Use outro número ou restaure o registro existente.';
  if(!validDate(values.received))errors.received='Informe a data de recebimento.';
  if(!validDate(values.deadline))errors.deadline='Informe um prazo válido.';
  if(!errors.received&&!errors.deadline&&values.deadline<values.received)errors.deadline='O prazo deve ser igual ou posterior ao recebimento.';
  if(Object.keys(errors).length){$('editor').inert=false;Object.entries(errors).forEach(([field,error])=>{$('error-'+field).textContent=error;$(field).setAttribute('aria-invalid','true');});$(Object.keys(errors)[0]).focus();return;}
  if(editing===null&&$('work-project').value)await workOverview.createLinked(values);
  else {
   if(editing!==null)rows=rows.map(row=>{if(row.id!==editing)return row;const updated={...row,...values};if(values.deadline!==row.deadline)delete updated.deadlineRule;return updated;});else rows.push({...values,id:nextId++,summary:summaryDefaults.pending,labels:Object.fromEntries(materials.map(m=>[m,defaults.notStarted]))});
   render();await persistence.ensureSaved();$('editor').close();
  }
  $('message').textContent='Romaneio '+values.reference+' gravado no computador.';
 }catch(error){$('work-action-message').textContent=error.message;}
 finally{delete $('editor').dataset.saving;$('editor').inert=false;}
});

['material-filter','stage-filter'].forEach(id=>$(id).addEventListener('change',render));$('search').addEventListener('input',render);

$('clear').addEventListener('click',()=>{$('search').value='';$('material-filter').value='';$('stage-filter').value='';render();});

$('customize').addEventListener('click',()=>{$('column-form').reset();$('stage-form').reset();$('column-error').textContent='';$('stage-error').textContent='';$('settings-message').textContent='';$('settings').showModal();});

$('settings-close').addEventListener('click',()=>$('settings').close());

$('column-form').addEventListener('submit',event=>{event.preventDefault();const name=$('column-name').value.trim(),error=columnError(name);$('column-error').textContent=error;if(error)return;createMaterialColumn(name);render();$('column-form').reset();$('settings-message').textContent='Coluna '+name+' criada. Nos romaneios existentes está em '+defaults.notApplicable+'; altere quando houver esse material.';});

$('stage-form').addEventListener('submit',event=>{event.preventDefault();const name=$('stage-name').value.trim();$('stage-error').textContent='';if(!name||stages.some(stage=>normalize(stage)===normalize(name))){$('stage-error').textContent=!name?'Informe o nome da etiqueta.':'Já existe uma etiqueta com esse nome.';return;}stages.push(name);customColors.set(name,$('stage-color').value);if($('stage-meaning').value==='purchased')purchased.add(name);const option=node('option',name);option.value=name;$('stage-filter').append(option);render();$('stage-form').reset();$('settings-message').textContent='Etiqueta '+name+' criada e disponível nas colunas de materiais.';});

setInterval(()=>{if(!columnDrag&&$('label-popover').hidden&&$('column-popover').hidden&&!$('editor').open&&!$('settings').open&&!$('cell-editor').open&&!$('work-trash').open&&!attachments?.isOpen()&&!$('sector-manager').open&&!$('sector-editor').open)render();},60000);


function exportState(filtersOverride=null){
 return {schema:1,...(workflowVersion?{workflowVersion,labelDescriptions:{...labelDescriptions}}:{}),materials:[...materials],fixedHeaders:{...fixedHeaders},stages:[...stages],customColors:[...customColors],excluded:[...excluded],summaryStages:[...summaryStages],summaryColors:[...summaryColors],summaryDone:[...summaryDone],summaryDefaults:{...summaryDefaults},defaults:{...defaults},purchased:[...purchased],rows:structuredClone(rows),nextId,columnSequence,viewColumns:structuredClone(viewColumns),typeValues:[...typeValues].map(([cid,works])=>[cid,[...works].map(([rid,types])=>[rid,[...types]])]),deletedColumns:[...deletedColumns],filters:filtersOverride||{search:$('search').value,material:$('material-filter').value,stage:$('stage-filter').value}};
}
function importState(state){
 workflowVersion=state.workflowVersion||0;Object.keys(labelDescriptions).forEach(k=>delete labelDescriptions[k]);Object.assign(labelDescriptions,state.labelDescriptions||{});
 const array=(target,source)=>target.splice(0,target.length,...structuredClone(source));
 const record=(target,source)=>{Object.keys(target).forEach(key=>delete target[key]);Object.entries(source).forEach(([key,value])=>Object.defineProperty(target,key,{value,writable:true,enumerable:true,configurable:true}));};
 array(materials,state.materials);record(fixedHeaders,state.fixedHeaders);array(stages,state.stages);customColors.clear();state.customColors.forEach(([k,v])=>customColors.set(k,v));excluded.clear();state.excluded.forEach(v=>excluded.add(v));array(summaryStages,state.summaryStages);summaryColors.clear();state.summaryColors.forEach(([k,v])=>summaryColors.set(k,v));summaryDone.clear();state.summaryDone.forEach(v=>summaryDone.add(v));record(summaryDefaults,state.summaryDefaults);record(defaults,state.defaults);purchased.clear();state.purchased.forEach(v=>purchased.add(v));rows=structuredClone(state.rows);nextId=state.nextId;columnSequence=state.columnSequence;array(viewColumns,state.viewColumns);typeValues.clear();state.typeValues.forEach(([cid,works])=>typeValues.set(cid,new Map(works.map(([rid,types])=>[rid,new Map(types)]))));array(deletedColumns,state.deletedColumns);refreshMaterialFilter(state.filters.material);refreshStageFilter(state.filters.stage);$('search').value=state.filters.search;
}

persistence=createPersistence({getState:exportState,applyState:importState,redraw:render,onLoaded:index=>workOverview?.loaded(index),onSaved:async state=>{await workOverview?.boardSaved(state);await attachments?.boardSaved(state);}});
const sectorController=createSectors({getPersistence:()=>persistence});
try {
 const sector=await sectorController.start();
 persistence.setSectorId(sector.id);
 attachments=createAttachments({persistence,redraw:render});
 workOverview=createWorkOverview({persistence,attachments,getRows:()=>rows,getColumns:()=>viewColumns,getEditing:()=>editing,openEditor,renderCell,columnName,redraw:render,isDirty:()=>{const row=rows.find(r=>r.id===editing);return !!row&&fields.some(f=>$(f).value!==(row[f]??''));}});
 const stored=await persistence.start();
 await attachments.start(stored);
 if(stored?.workflowVersion===1){flow=createFlow({persistence,attachments,sector,getRows:()=>rows,reload:async()=>{const state=await persistence.start();await attachments.start(state);}});await flow.start();render();}
} catch(error) {
 $('storage-status').textContent='Não foi possível carregar os setores';
 $('storage-status').dataset.mode='error';
 $('storage-detail').textContent=error.message;
}
})();

