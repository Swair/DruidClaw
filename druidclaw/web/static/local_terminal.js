/**
 * DruidClaw - Local Terminal Connection
 *
 * 管理本地终端连接
 */

// 用户点击"新建本地终端"快捷按钮
async function addLocalSessionToCurrentServer() {
  let localSrv = servers.find(s => s.type === 'local');
  if (!localSrv) {
    const srvId = `term${++_srvIdSeq}`;
    localSrv = { id:srvId, label:'🖥 本地', type:'local',
                  status:'ok', sessions:{}, activeSession:null, terms:{} };
    servers.push(localSrv);
    activeSrvId = srvId;
    renderServerBar();
    renderCards();
  } else {
    activeSrvId = localSrv.id;
    renderServerBar();
    renderCards();
  }
  const sessName = `local_${Date.now()%10000}`;
  await openLocalTerminal(localSrv, sessName, '', null);
  saveSessionsToStorage();
}

// 用户从模态框创建本地终端
async function connectLocalShell() {
  const shellOverride = document.getElementById('local-shell')?.value.trim() || '';
  closeSrvModal();
  let localSrv = servers.find(s => s.type === 'local');
  const sessName = `local_${Date.now()%10000}`;
  if (!localSrv) {
    const srvId = `term${++_srvIdSeq}`;
    localSrv = { id:srvId, label:'🖥 本地', type:'local',
                  status:'ok', sessions:{}, activeSession:null, terms:{} };
    servers.push(localSrv);
    activeSrvId = srvId;
    renderServerBar();
    renderCards();
  } else {
    activeSrvId = localSrv.id;
    renderServerBar();
    renderCards();
  }
  await openLocalTerminal(localSrv, sessName, shellOverride, null);
  saveSessionsToStorage();
}

// 打开本地终端（内部函数）
async function openLocalTerminal(srv, name, shellOverride, ownSrvId) {
  const term = new Terminal({
    cursorBlink: true, fontSize: 14, fontFamily: 'monospace',
    theme: _xtermTheme(),
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());

  srv.sessions[name] = { ws: null, term, fitAddon: fit, status: 'connecting', pid: null, lastOutputAt: 0, shell: shellOverride };
  srv.activeSession = name;
  hideFeishuView();
  renderSessionList();
  restoreTerminal();
  safeFit(srv, name);

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/local/${encodeURIComponent(name)}`);
  srv.sessions[name].ws = ws;

  ws.onopen = () => {
    const { rows, cols } = term;
    ws.send(JSON.stringify({ type: 'local_connect', shell: shellOverride, rows, cols }));
  };

  ws.onmessage = evt => {
    let msg; try { msg = JSON.parse(evt.data); } catch { return; }
    if (msg.type === 'output') {
      term.write(Uint8Array.from(atob(msg.data), c => c.charCodeAt(0)));
      if (srv.sessions[name]) srv.sessions[name].lastOutputAt = Date.now();
    } else if (msg.type === 'connected') {
      if (srv.sessions[name]) { srv.sessions[name].status = 'alive'; srv.sessions[name].pid = msg.pid; }
      renderSessionList(); renderCards(); updateToolbar();
      toast(t('local_terminal') + t('toast_connected') + ` (pid=${msg.pid})`);
    } else if (msg.type === 'exit') {
      if (srv.sessions[name]) srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
      term.write('\r\n\x1b[33m[本地终端已关闭，2 秒后关闭卡片]\x1b[0m\r\n');
      setTimeout(() => killSessionByName(srv.id, name), 2000);
    } else if (msg.type === 'error') {
      if (srv.sessions[name]) srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
      term.write(`\r\n\x1b[31m[错误：${msg.message}]\x1b[0m\r\n`);
      setTimeout(() => killSessionByName(srv.id, name), 3000);
    }
  };

  ws.onclose = () => {
    if (srv.sessions[name] && srv.sessions[name].status === 'alive') {
      srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
    }
  };

  term.onData(data => {
    if (ws.readyState === WebSocket.OPEN) {
      const bytes = new TextEncoder().encode(data);
      ws.send(JSON.stringify({ type: 'input', data: btoa(String.fromCharCode(...bytes)) }));
    }
  });
  term.onResize(({ rows, cols }) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type:'resize', rows, cols }));
  });
}
