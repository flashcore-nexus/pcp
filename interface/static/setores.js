// O cadastro usa a mesma API local; navegar troca o quadro sem copiar dados da aba.
export function createSectors({getPersistence}) {
  const $ = id => document.getElementById(id);
  let registry = null, selected = null, editing = null, busy = false;
  const make = (tag, text, cls) => {const element = document.createElement(tag); if (text !== undefined) element.textContent = text; if (cls) element.className = cls; return element;};
  const manager = $('sector-manager'), editor = $('sector-editor');
  function notice(message, error = false) {
    $('sector-message').textContent = message;
    $('sector-message').className = error ? 'error' : 'notice';
  }
  async function load() {
    const response = await fetch('/api/sectors', {cache: 'no-store'});
    if (!response.ok) throw new Error('Não foi possível carregar os setores. Atualize a página para tentar novamente.');
    registry = await response.json(); render();
  }
  async function navigate(id) {
    if (busy) return;
    try {await getPersistence().ensureSaved(); location.assign('/?sector=' + encodeURIComponent(id));}
    catch (error) {$('message').textContent = error.message; notice(error.message, true);}
  }
  function heading(sector) {
    document.title = 'PCP · ' + sector.name;
    document.querySelector('.top h1').textContent = sector.name + ', etapa por etapa.';
    if (sector.name === 'Comercial') {document.querySelector('.banner').textContent='Comercial técnico: valores e documentos restritos ainda indisponíveis até a implementação de autenticação e permissões no servidor.';}
    if (sector.is_primary) return;
    document.querySelector('.eyebrow').textContent = 'QUADRO DO SETOR';
    document.querySelector('.top p').textContent = sector.description || 'Obras compartilhadas, etapas e informações próprias deste setor.';
    $('pending-heading').textContent = sector.name + ' · em andamento';
    $('done-heading').textContent = sector.name === 'Comercial' ? 'Obras vendidas' : sector.name + ' · concluídas';if(sector.name==='Comercial')$('pending-heading').textContent='Orçamentos em andamento';
    document.querySelector('.stats .stat:nth-child(1) span').textContent = 'Obras cadastradas';
    document.querySelector('.stats .stat:nth-child(2) span').textContent = 'Em andamento';
    document.querySelector('.stats .stat:nth-child(3) span').textContent = 'Aguardando liberação';
    document.querySelector('.stats .stat:nth-child(4) span').textContent = 'Concluídas';
    document.querySelector('.layoutnote').textContent = 'Cada obra tem a mesma identidade e nome em todos os setores. Etapas, responsáveis, prazos, colunas, filtros e anexos pertencem a este quadro. As etiquetas do status geral são sempre manuais.';
    $('pending-empty').textContent = 'Nenhuma obra em andamento para os filtros atuais.';
    $('done-empty').textContent = 'Nenhuma obra concluída para os filtros atuais.';
    document.querySelector('.navnote').textContent = 'Uma obra por linha. Os dados operacionais e documentos ficam no respectivo setor.';
  }
  function render() {
    if (!registry) return;
    const nav = $('sector-nav'); nav.replaceChildren();
    for (const sector of registry.sectors.filter(s => s.active)) {
      const row = make('div', undefined, 'sector-nav-row');
      const button = make('button', undefined, 'navitem sector-nav-button'); button.type = 'button';
      const icon = make('span', sector.icon, 'sector-icon'); icon.style.color = sector.color;
      button.append(icon, make('span', sector.name, 'sector-nav-name'));
      button.title = sector.description || sector.name;
      if (selected?.id === sector.id) button.setAttribute('aria-current', 'page');
      button.addEventListener('click', () => navigate(sector.id));
      const edit = make('button', '⋯', 'sector-more'); edit.type = 'button'; edit.setAttribute('aria-label', 'Editar setor ' + sector.name);
      edit.addEventListener('click', () => openEditor(sector)); row.append(button, edit); nav.append(row);
    }
    if (selected) {
      selected = registry.sectors.find(s => s.id === selected.id) || selected;
      if (selected.active) heading(selected);
    }
    renderManager();
  }
  function renderManager() {
    const list = $('sector-list'); list.replaceChildren();
    const activeCount = registry.sectors.filter(s => s.active).length;
    registry.sectors.forEach((sector, index) => {
      const row = make('div', undefined, 'sector-manager-row');
      const info = make('div'); info.append(make('strong', sector.icon + ' ' + sector.name), make('span', (sector.active ? 'Ativo' : 'Inativo') + ' · ' + sector.works + ' obras · ' + sector.documents + ' anexos', 'sub'));
      if (sector.description) info.append(make('span', sector.description, 'sub'));
      const tools = make('div', undefined, 'sector-tools');
      for (const [label, direction] of [['↑', -1], ['↓', 1]]) {
        const button = make('button', label, 'secondary'); button.type = 'button';
        button.disabled = busy || index + direction < 0 || index + direction >= registry.sectors.length;
        button.setAttribute('aria-label', (direction < 0 ? 'Subir ' : 'Descer ') + sector.name);
        button.addEventListener('click', () => {
          const ids = registry.sectors.map(s => s.id); [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
          mutate({action: 'reorder', ids});
        }); tools.append(button);
      }
      const edit = make('button', 'Editar', 'secondary'); edit.type = 'button'; edit.disabled = busy; edit.addEventListener('click', () => openEditor(sector)); tools.append(edit);
      const toggle = make('button', sector.active ? 'Inativar' : 'Reativar', 'secondary'); toggle.type = 'button'; toggle.disabled = busy || (sector.active && activeCount === 1);
      if (sector.active && activeCount === 1) toggle.title = 'É necessário manter pelo menos um setor ativo.';
      toggle.addEventListener('click', () => {
        if (sector.active && !confirm('Inativar “' + sector.name + '”? Suas ' + sector.works + ' obras e ' + sector.documents + ' anexos serão preservados. Você poderá reativá-lo depois.')) return;
        mutate({action: 'active', id: sector.id, active: !sector.active, confirm: true});
      }); tools.append(toggle); row.append(info, tools); list.append(row);
    });
  }
  async function mutate(payload) {
    if (busy) return false;
    let success = false;
    busy = true; editor.querySelectorAll('input,textarea,select,button').forEach(e => {e.disabled = true;}); $('sector-error').textContent = ''; notice('Salvando setores no computador…'); renderManager();
    try {
      await getPersistence().ensureSaved();
      registry = await getPersistence().request('/api/sectors', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...payload, revision: registry.revision})});
      notice('Setores gravados no computador.'); render();
      success = true;
    } catch (error) {notice(error.message, true); $('sector-error').textContent = error.message;}
    finally {busy = false; editor.querySelectorAll('input,textarea,select,button').forEach(e => {e.disabled = false;}); renderManager();}
    if (success && selected && !registry.sectors.find(s => s.id === selected.id)?.active) await navigate(registry.sectors.find(s => s.active).id);
    return success;
  }
  function openEditor(sector = null) {
    if (busy) return;
    editing = sector;
    $('sector-editor-title').textContent = sector ? 'Editar setor' : 'Adicionar Setor';
    $('sector-name').value = sector?.name || '';
    $('sector-description').value = sector?.description || '';
    $('sector-color').value = sector?.color || '#315acb';
    const icons = $('sector-icon'); icons.replaceChildren();
    for (const icon of registry.icons) {const option = make('option', icon); option.value = icon; icons.append(option);}
    icons.value = sector?.icon || '▦'; $('sector-error').textContent = '';
    if (!editor.open) editor.showModal(); $('sector-name').focus();
  }
  $('sector-add').addEventListener('click', () => openEditor());
  $('sector-manage').addEventListener('click', async () => {
    if (busy) return;
    try {await load(); notice('Use as setas para ordenar. Inativar preserva os dados.'); if (!manager.open) manager.showModal();}
    catch (error) {$('message').textContent = error.message;}
  });
  $('sector-refresh').addEventListener('click', async () => {if (!busy) {try {await load(); notice('Lista atualizada.');} catch (error) {notice(error.message, true);}}});
  $('sector-manager-close').addEventListener('click', () => {if (!busy) manager.close();});
  $('sector-editor-close').addEventListener('click', () => {if (!busy) editor.close();});
  for (const dialog of [manager, editor]) dialog.addEventListener('cancel', event => {if (busy) event.preventDefault();});
  $('sector-form').addEventListener('submit', async event => {
    event.preventDefault();
    const name = $('sector-name').value.trim();
    if (!name) {$('sector-error').textContent = 'Informe o nome do setor.'; $('sector-name').focus(); return;}
    const success = await mutate({action: editing ? 'edit' : 'create', ...(editing ? {id: editing.id} : {}), name, description: $('sector-description').value, color: $('sector-color').value, icon: $('sector-icon').value});
    if (success) {editor.close(); if (!editing) await navigate(registry.changed_id);}
  });
  return {async start() {
    await load();
    const requested = new URLSearchParams(location.search).get('sector');
    selected = registry.sectors.find(s => s.id === requested && s.active) || registry.sectors.find(s => s.active);
    if (!selected) throw new Error('Nenhum setor ativo disponível.');
    window.history.replaceState(null, '', '/?sector=' + encodeURIComponent(selected.id)); render(); return selected;
  }};
}
