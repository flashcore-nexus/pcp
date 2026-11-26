// Arquivos ficam no servidor local; a interface mantém apenas a lista de metadados.
export function fileSize(bytes) {
  return bytes < 1024 ? bytes + ' B' : bytes < 1048576 ? (bytes / 1024).toFixed(1) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB';
}

export function createAttachments({persistence, redraw}) {
  let cells = [], config = null, selected = null, busy = false, loaded = false;
  let requestIndex = 0, lastColumns = null;
  const columnShape = state => JSON.stringify((state?.viewColumns || []).map(c => [c.id, c.type, !!c.deleted]));
  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const dialog = make('dialog'); dialog.id = 'attachment-dialog';
  dialog.setAttribute('aria-labelledby', 'attachment-title');
  dialog.innerHTML = '<div class="dialoghead"><h2 id="attachment-title">Anexos da célula</h2><button type="button" class="close" aria-label="Fechar anexos">×</button></div><p class="muted" id="attachment-context"></p><p class="muted" id="attachment-limits"></p><div id="attachment-files"></div><p role="status" aria-live="polite" id="attachment-status"></p><div class="dialogactions"><button type="button" class="primary" id="attachment-add">+ Anexar arquivo</button></div><input type="file" id="attachment-input" multiple hidden>';
  document.body.append(dialog);
  const field = id => dialog.querySelector('#attachment-' + id);
  const status = (text, error = false) => {field('status').textContent = text; field('status').className = error ? 'error' : 'notice';};
  dialog.querySelector('.close').addEventListener('click', () => dialog.close());
  field('add').addEventListener('click', () => field('input').click());
  const find = (work, column) => cells.find(c => c.work_id === work && c.column_id === column);
  const url = (cell, file, action) => '/api/cells/' + encodeURIComponent(cell.id) + '/attachments' + (file ? '/' + encodeURIComponent(file.id) + '/' + action : '');
  function setBusy(value) {
    busy = value;
    dialog.querySelectorAll('button,input').forEach(element => {element.disabled = value;});
    if (!value && config && !config.uploads_enabled) field('add').disabled = true;
  }
  dialog.addEventListener('cancel', event => {if (busy) event.preventDefault();});
  async function refresh() {
    const generation = ++requestIndex;
    const result = await persistence.request('/api/attachments');
    if (generation !== requestIndex) return false;
    cells = result.cells; config = result.config; loaded = true;
    field('input').accept = config.allowed_extensions.join(',');
    redraw();
    return true;
  }
  async function change(cell, file, action, payload) {
    if (busy) return;
    setBusy(true);
    try {
      await persistence.request(url(cell, file, action), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      await refresh(); showList(); status(action === 'delete' ? 'Anexo removido da célula.' : 'Nome gravado no computador.');
    } catch (error) {status(error.message, true);}
    finally {setBusy(false);}
  }
  function showList() {
    const cell = selected && find(selected.work, selected.column);
    const list = field('files'); list.replaceChildren();
    field('context').textContent = selected ? selected.title : '';
    field('limits').textContent = config ? 'Até ' + fileSize(config.max_file_bytes) + ' por arquivo · ' + config.max_files_per_cell + ' arquivos por célula. PDF, imagens, Word, Excel, DWG, DXF e ZIP. Prévia para PDF e imagens, conforme o navegador.' : 'Carregando anexos…';
    if (!cell || !cell.files.length) list.append(make('p', 'Nenhum arquivo nesta célula.', 'muted'));
    for (const file of cell?.files || []) {
      const row = make('div', undefined, 'attachment-item');
      const name = make('strong', file.name, 'attachment-name'); name.title = file.name;
      row.append(name, make('span', fileSize(file.size), 'muted'));
      const actions = make('div', undefined, 'attachment-actions');
      if (file.preview) {
        const view = make('a', 'Visualizar'); view.href = url(cell, file, 'preview'); view.target = '_blank'; view.rel = 'noopener noreferrer'; actions.append(view);
      } else actions.append(make('span', 'Sem prévia; baixe para abrir.', 'muted'));
      const download = make('a', 'Baixar'); download.href = url(cell, file, 'download'); actions.append(download);
      const rename = make('button', 'Renomear', 'secondary'); rename.type = 'button';
      rename.addEventListener('click', () => {const name = prompt('Novo nome, mantendo a extensão:', file.name); if (name && name !== file.name) change(cell, file, 'rename', {name});});
      const remove = make('button', 'Excluir', 'secondary'); remove.type = 'button';
      remove.addEventListener('click', () => {if (confirm('Excluir “' + file.name + '” desta célula?')) change(cell, file, 'delete', {confirm: true});});
      actions.append(rename, remove); row.append(actions); list.append(row);
    }
  }
  async function open(work, column, title, files = null) {
    if (busy) return;
    selected = {work, column, title};
    status('Carregando anexos…'); showList(); if (!dialog.open) dialog.showModal();
    setBusy(true);
    try {
      await persistence.ensureSaved(); await refresh(); showList(); status('Arquivos armazenados neste computador.');
    } catch (error) {status(error.message, true); files = null;}
    finally {setBusy(false);}
    if (files) await upload(files);
  }
  async function upload(files) {
    if (busy || !selected) return;
    setBusy(true); let saved = 0; const errors = [];
    try {
      await persistence.ensureSaved(); await refresh();
      const cell = find(selected.work, selected.column);
      if (!cell) throw new Error('Esta célula não está mais disponível. Reabra o quadro gravado.');
      if (!config.uploads_enabled) throw new Error('Envio de arquivos desativado na configuração local.');
      for (const file of Array.from(files)) {
        status('Gravando ' + file.name + '… Aguarde a confirmação.');
        try {
          if (!file.size || file.size > config.max_file_bytes) throw new Error('Arquivo vazio ou acima de ' + fileSize(config.max_file_bytes) + '.');
          await persistence.request(url(cell), {method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-PCP-Filename': encodeURIComponent(file.name)}, body: file});
          saved++;
        } catch (error) {errors.push(file.name + ': ' + error.message);}
      }
      await refresh(); showList();
      status(saved + ' arquivo(s) confirmado(s) no disco.' + (errors.length ? ' Sem confirmação: ' + errors.join(' · ') : ''), errors.length > 0);
    } catch (error) {status(error.message + (saved ? ' Já confirmado(s): ' + saved + '.' : ''), true);}
    finally {field('input').value = ''; setBusy(false);}
  }
  field('input').addEventListener('change', event => upload(event.target.files));
  function decorate(element, column, work, title, expanded = false) {
    const cell = find(work, column), files = cell?.files || [];
    element.classList.add('attachment-cell');
    const button = make('button', undefined, 'cell-attachments'); button.type = 'button';
    const caption = files.length ? expanded ? '📎 Gerenciar anexos (' + files.length + ')' : '📎 ' + files[0].name : '📎 + Anexar arquivo';
    button.append(make('span', caption, 'cell-file-name'));
    if (files.length) button.append(make('span', fileSize(files[0].size) + (files.length > 1 ? ' · +' + (files.length - 1) + ' arquivos' : ''), 'cell-file-detail'));
    button.title = files.length ? files[0].name + ' — abrir lista de anexos' : 'Anexar arquivo por clique ou arraste';
    button.setAttribute('aria-label', title + ' — ' + (loaded ? caption : 'carregar anexos'));
    button.addEventListener('click', () => open(work, column, title)); element.append(button);
    if (expanded && files.length) {
      const list = make('div', undefined, 'overview-file-list');
      for (const file of files) {
        const entry = make('div', undefined, 'overview-file');
        entry.append(make('span', file.name, 'attachment-name'), make('span', fileSize(file.size), 'muted'));
        if (file.preview) {const preview = make('a', 'Visualizar'); preview.href = url(cell, file, 'preview'); preview.target = '_blank'; preview.rel = 'noopener noreferrer'; entry.append(preview);}
        const download = make('a', 'Baixar'); download.href = url(cell, file, 'download'); entry.append(download); list.append(entry);
      }
      element.append(list);
    }
    let depth = 0;
    const isFile = event => Array.from(event.dataTransfer?.types || []).includes('Files');
    element.addEventListener('dragenter', event => {if (isFile(event)) {event.preventDefault(); depth++; element.classList.add('file-drag-over');}});
    element.addEventListener('dragover', event => {if (isFile(event)) {event.preventDefault(); event.dataTransfer.dropEffect = 'copy';}});
    element.addEventListener('dragleave', () => {if (--depth <= 0) {depth = 0; element.classList.remove('file-drag-over');}});
    element.addEventListener('drop', event => {
      if (!isFile(event)) return;
      event.preventDefault(); event.stopPropagation(); depth = 0; element.classList.remove('file-drag-over');
      open(work, column, title, Array.from(event.dataTransfer.files));
    });
  }
  // Impede o navegador de abandonar o quadro ao soltar arquivos fora das células.
  for (const name of ['dragover', 'drop']) document.addEventListener(name, event => {if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault();});
  return {decorate, async start(state) {lastColumns = columnShape(state); try {await refresh();} catch (error) {document.getElementById('message').textContent = 'Anexos não carregados: ' + error.message + ' Clique em Anexar arquivo para tentar novamente.';}},
    async boardSaved(state) {
      const next = columnShape(state);
      if (next === lastColumns) return;
      lastColumns = next;
      try {if (await refresh() && dialog.open) showList();}
      catch (error) {if (lastColumns === next) lastColumns = null; document.getElementById('message').textContent = 'O quadro foi gravado; atualize os anexos pelo clipe. ' + error.message;}
    }, isOpen: () => dialog.open};
}
