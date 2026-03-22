/**
 * DruidClaw - Claude Code Session Management
 *
 * 管理 Claude Code 会话（HTTP 连接）
 */

// 用户点击"新建会话"按钮
async function createSession() {
  const srv = activeSrv();
  if (!srv) { toast(t('toast_select_server'), true); return; }
  const btn = document.getElementById('btn-create');
  btn.disabled = true;
  const name    = document.getElementById('s-name').value.trim() || null;
  const workdir = document.getElementById('s-dir').value.trim()  || '.';
  const argsRaw = document.getElementById('s-args').value.trim();
  const args    = argsRaw ? argsRaw.split(/\s+/) : [];
  try {
    const r = await fetch(`${srvBase(srv)}/api/sessions`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, workdir, args })
    });
    const d = await r.json();
    if (d.error) { toast('创建失败：' + d.error, true); return; }
    document.getElementById('s-name').value = '';
    if (d.dir_created) toast(`已自动创建目录：${d.workdir}`);
    connectSession(srv, d.name);
  } catch (e) {
    toast('创建失败：' + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

// 用户点击"终止"按钮
async function killActive() {
  const srv = activeSrv();
  if (!srv || !srv.activeSession) return;
  const name = srv.activeSession;
  if (!confirm(`终止会话 "${name}"？`)) return;
  try {
    await fetch(`${srvBase(srv)}/api/sessions/${encodeURIComponent(name)}?force=true`, { method: 'DELETE' });
  } catch (_) {}
  const s = srv.sessions[name];
  if (s) { s.status = 'dead'; renderSessionList(); updateToolbar(); }
}

// 连接会话（内部函数）
function connectSession(srv, name) {
  srv.activeSession = name;
  renderSessionList();
  renderCards();
  updateToolbar();

  if (srv.sessions[name] && srv.sessions[name].ws &&
      srv.sessions[name].ws.readyState <= WebSocket.OPEN) {
    restoreTerminal();
    safeFit(srv, name);
    setTimeout(() => { renderCards(); }, 100);
    return;
  }

  const { term, fit } = createTerminal();
  const ws = new WebSocket(wsUrl(srv, name));
  srv.sessions[name] = { ws, term, fitAddon: fit, status: 'connecting', pid: null, lastOutputAt: 0 };
  renderSessionList();
  renderCards();
  updateToolbar();
  restoreTerminal();

  ws.onopen = () => setTimeout(() => safeFit(srv, name), 60);
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'output') {
      term.write(Uint8Array.from(atob(msg.data), c => c.charCodeAt(0)));
      if (srv.sessions[name]) {
        srv.sessions[name].lastOutputAt = Date.now();
        updateDot(srv, name);
      }
    } else if (msg.type === 'connected') {
      srv.sessions[name].status = 'alive';
      srv.sessions[name].pid = msg.pid;
      renderSessionList(); updateToolbar();
      toast(`已连接 "${name}" (pid=${msg.pid})`);
    } else if (msg.type === 'exit') {
      srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
      term.write('\r\n\x1b[33m[会话已退出]\x1b[0m\r\n');
    } else if (msg.type === 'error') {
      srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
      term.write(`\r\n\x1b[31m[错误：${msg.message}]\x1b[0m\r\n`);
    }
  };
  ws.onclose = () => {
    if (srv.sessions[name] && srv.sessions[name].status !== 'dead') {
      srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
    }
  };
  term.onData(data => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type:'input', data: btoa(String.fromCharCode(...new TextEncoder().encode(data))) }));
    }
  });
}
