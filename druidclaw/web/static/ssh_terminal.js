/**
 * DruidClaw - SSH Terminal Connection
 *
 * 管理 SSH 远程终端连接
 */

// 用户点击 SSH 服务器"+"按钮 - 使用已有参数创建新会话
async function addSshSessionToCurrentServer() {
  const srv = activeSrv();
  if (!srv || srv.type !== 'ssh') return;

  // 从已有会话获取连接参数
  const firstSess = srv.sessions && Object.values(srv.sessions)[0];
  const params = firstSess?.params || {};

  if (!params || !params.host || !params.username) {
    // 没有保存的参数，打开模态框
    openSshConnect();
    return;
  }

  const sessName = `ssh_${params.host}_${Date.now()%10000}`;
  await openSshTerminal(srv, sessName, params, srv.id);
  saveSessionsToStorage();
}

// 用户从模态框创建 SSH 连接
async function connectSSH() {
  const host  = document.getElementById('ssh-host').value.trim();
  const user  = document.getElementById('ssh-user').value.trim();
  const pass  = document.getElementById('ssh-pass').value;
  const key   = document.getElementById('ssh-key').value.trim();
  const label = document.getElementById('ssh-label').value.trim() || `${user}@${host}`;
  const port  = parseInt(document.getElementById('ssh-port').value) || 22;

  if (!host || !user) { toast(t('toast_fill_host_user'), true); return; }

  const savePassCheckbox = document.getElementById('ssh-save-pass');
  const savePass = savePassCheckbox ? savePassCheckbox.checked : false;

  closeSrvModal();

  let sshSrv = servers.find(s => s.type === 'ssh' && s.host === host && s.port === port);
  if (!sshSrv) {
    const srvId = `term${++_srvIdSeq}`;
    const sshLabel = `🔒 ${label}`;
    sshSrv = { id:srvId, label:sshLabel, type:'ssh', host, port,
               status:'ok', sessions:{}, activeSession:null, terms:{} };
    servers.push(sshSrv);
    activeSrvId = srvId;
    renderServerBar();
    renderCards();
  } else {
    activeSrvId = sshSrv.id;
    renderServerBar();
    renderCards();
  }

  const sessName = `ssh_${host}_${Date.now()%10000}`;
  await openSshTerminal(sshSrv, sessName, { host, port, username: user,
                                             password: pass, key_path: key, label, save_password: savePass }, sshSrv.id);

  saveSessionsToStorage();
}

// 打开 SSH 终端（内部函数）
async function openSshTerminal(srv, name, params, ownSrvId) {
  const { createTerminal, FitAddon } = _getTerminalConstructors();
  const term = createTerminal();
  const fit  = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());

  srv.sessions[name] = { ws: null, term, fitAddon: fit, status: 'connecting', pid: null, lastOutputAt: 0, params };
  srv.activeSession = name;
  hideFeishuView();
  renderSessionList();
  restoreTerminal();
  safeFit(srv, name);

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/ssh/${encodeURIComponent(name)}`);
  srv.sessions[name].ws = ws;

  ws.onopen = () => {
    const { rows, cols } = term;
    ws.send(JSON.stringify({
      type: 'ssh_connect',
      host: params.host,
      port: params.port,
      username: params.username,
      password: params.password,
      key_path: params.key_path,
      rows, cols
    }));
  };

  ws.onmessage = evt => {
    let msg; try { msg = JSON.parse(evt.data); } catch { return; }
    if (msg.type === 'output') {
      term.write(Uint8Array.from(atob(msg.data), c => c.charCodeAt(0)));
      if (srv.sessions[name]) srv.sessions[name].lastOutputAt = Date.now();
    } else if (msg.type === 'connected') {
      if (srv.sessions[name]) { srv.sessions[name].status = 'alive'; srv.sessions[name].pid = msg.pid; }
      renderSessionList(); renderCards(); updateToolbar();
      toast(t('ssh_terminal') + t('toast_connected') + ` (pid=${msg.pid})`);
    } else if (msg.type === 'auth_failed') {
      if (srv.sessions[name]) srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
      term.write(`\r\n\x1b[31m[SSH 认证失败：${params.username}@${params.host}]\x1b[0m\r\n`);
      setTimeout(() => killSessionByName(srv.id, name), 2500);
    } else if (msg.type === 'error') {
      if (srv.sessions[name]) srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
      term.write(`\r\n\x1b[31m[SSH 错误：${msg.message}]\x1b[0m\r\n`);
      setTimeout(() => killSessionByName(srv.id, name), 3000);
    } else if (msg.type === 'exit') {
      if (srv.sessions[name]) srv.sessions[name].status = 'dead';
      renderSessionList(); updateToolbar();
      term.write('\r\n\x1b[33m[SSH 终端已关闭]\x1b[0m\r\n');
      setTimeout(() => killSessionByName(srv.id, name), 2000);
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
