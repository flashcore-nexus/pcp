// Confirmação de gravação só depois do COMMIT do servidor.
export function createPersistence({getState, applyState, redraw, sectorId = null, onSaved = null, onLoaded = null}) {
  let revision = 0, csrf = '', lastSaved = '', ready = false;
  let timer = null, busy = false, blocked = false;
  const scoped = url => sectorId ? url + (url.includes('?') ? '&' : '?') + 'sector=' + encodeURIComponent(sectorId) : url;
  const status = document.getElementById('storage-status');
  const detail = document.getElementById('storage-detail');
  const retry = document.getElementById('storage-retry');
  const draft = document.getElementById('storage-draft');
  const reopen = document.getElementById('storage-reopen');

  function show(mode, message, explanation = '') {
    status.textContent = message;
    status.dataset.mode = mode;
    detail.textContent = explanation;
    retry.hidden = mode !== 'error';
    draft.hidden = mode !== 'error' || !ready;
    reopen.hidden = mode !== 'error' || !ready;
    document.documentElement.dataset.storage = mode;
  }
  function lock(value) {
    document.querySelectorAll('button,input,select,textarea').forEach(element => {
      if (!element.hasAttribute('data-storage-control')) element.disabled = value;
    });
  }
  function notify() {
    if (!ready || blocked) return;
    const current = JSON.stringify(getState());
    if (current === lastSaved) return;
    show('saving', 'Salvando no computador…', 'Aguarde a confirmação antes de fechar a página.');
    clearTimeout(timer);
    timer = setTimeout(flush, 180);
  }
  async function start() {
    lock(true);
    show('loading', 'Carregando dados do computador…');
    try {
      const response = await fetch(scoped('/api/state'), {cache: 'no-store'});
      if (!response.ok) throw new Error('O servidor não conseguiu carregar os dados.');
      const payload = await response.json();
      if (!payload.state || !payload.csrf || !Number.isInteger(payload.revision)) throw new Error('Resposta do armazenamento inválida.');
      if (onLoaded) onLoaded(payload.works);
      applyState(payload.state);
      csrf = payload.csrf;
      revision = payload.revision;
      lastSaved = JSON.stringify(getState());
      blocked = false;
      ready = true;
      lock(false);
      redraw();
      show('ready', 'Dados carregados do computador', 'SQLite local · salvamento automático com confirmação.');
      return payload.state;
    } catch (error) {
      show('error', 'Não foi possível carregar o PCP', error.message + ' As edições estão bloqueadas para proteger os dados.');
    }
  }
  async function flush() {
    if (!ready || blocked || busy) return;
    const serialized = JSON.stringify(getState());
    if (serialized === lastSaved) return;
    busy = true;
    try {
      const response = await fetch(scoped('/api/state'), {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-PCP-CSRF': csrf},
        body: JSON.stringify({revision, state: JSON.parse(serialized)})
      });
      const payload = await response.json();
      if (!response.ok) {
        blocked = true;
        throw new Error(payload.error || 'O armazenamento não confirmou a gravação.');
      }
      if (!Number.isInteger(payload.revision)) throw new Error('O servidor não confirmou a revisão gravada.');
      revision = payload.revision;
      lastSaved = serialized;
      if (payload.state) {
        if (JSON.stringify(getState()) !== serialized) throw new Error('O nome compartilhado da obra foi gravado, mas há novas edições nesta aba. Preserve o rascunho e reabra a versão salva para continuar.');
        applyState(payload.state);
        lastSaved = JSON.stringify(getState());
        redraw();
      }
      const confirmed = lastSaved;
      if (onSaved) Promise.resolve().then(() => onSaved(JSON.parse(confirmed))).catch(() => {
        document.getElementById('message').textContent = 'O quadro foi gravado; não foi possível atualizar a lista de anexos. Clique no clipe para recarregar.';
      });
      if (JSON.stringify(getState()) === lastSaved) show('ready', 'Gravado no computador', 'Você pode fechar e abrir o PCP novamente.');
    } catch (error) {
      blocked = true;
      show('error', 'Há alterações não gravadas', error.message + ' Mantenha a aba aberta. Você pode baixar uma cópia das alterações pendentes.');
    } finally {
      busy = false;
      if (!blocked && JSON.stringify(getState()) !== lastSaved) notify();
    }
  }
  retry.addEventListener('click', () => {
    if (!ready) return start();
    blocked = false;
    notify();
    return flush();
  });
  draft.addEventListener('click', () => {
    const blob = new Blob([JSON.stringify({exportedAt: new Date().toISOString(), revision, state: getState()}, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'PCP-alteracoes-pendentes.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  reopen.addEventListener('click', () => {
    if (confirm('Reabrir a versão gravada no computador? As alterações pendentes desta aba não serão mantidas. Baixe a cópia pendente antes, se precisar preservá-las.')) location.reload();
  });
  window.addEventListener('beforeunload', event => {
    if (ready && (blocked || JSON.stringify(getState()) !== lastSaved)) {
      event.preventDefault(); event.returnValue = '';
    }
  });
  async function ensureSaved() {
    if (!ready || blocked) throw new Error('Primeiro resolva a gravação pendente do quadro.');
    clearTimeout(timer);
    for (;;) {
      while (busy) await new Promise(resolve => setTimeout(resolve, 30));
      if (blocked) throw new Error('A gravação não foi confirmada. Mantenha a aba aberta e resolva a pendência antes de continuar.');
      if (JSON.stringify(getState()) === lastSaved) return;
      await flush();
    }
  }
  async function request(url, options = {}) {
    if (!ready || blocked) throw new Error('Reabra a versão gravada do PCP antes de enviar anexos.');
    const response = await fetch(scoped(url), {...options, cache: 'no-store', headers: {...options.headers, 'X-PCP-CSRF': csrf}});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Operação com anexo não confirmada.');
    return payload;
  }
  lock(true);
  return {start, notify, flush, ensureSaved, request, setSectorId(value) {if (ready) throw new Error('Reabra a página para trocar de setor.'); sectorId = value;}};
}
