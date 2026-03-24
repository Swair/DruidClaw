/**
 * DruidClaw - Connection Management
 *
 * 管理 HTTP/Local/SSH 三种连接类型
 * 包含：连接类型选择、SSH 历史、服务器添加/切换/删除
 */

// Global state (shared with main.js)
let _connType = 'http';
let servers = [];       // ordered list
let activeSrvId = null;
let _srvIdSeq = 0;

// 根据 ID 获取服务器
function srvById(id) { return servers.find(s => s.id === id); }
// 获取当前活动服务器
function activeSrv() { return srvById(activeSrvId); }

// Session persistence
const SESSION_STORAGE_KEY = 'druidclaw_sessions';

// ── Connection type selector ────────────────────────────────
// 用户点击连接类型选项卡时触发 (HTTP/本地/SSH)
function selectConnType(type) {
  _connType = type;
  document.getElementById('ct-http').classList.toggle('sel',  type==='http');
  document.getElementById('ct-local').classList.toggle('sel', type==='local');
  document.getElementById('ct-ssh').classList.toggle('sel',   type==='ssh');
  document.getElementById('conn-http-fields').style.display  = type==='http'  ? '' : 'none';
  const localFields = document.getElementById('conn-local-fields');
  if (localFields) localFields.style.display = type==='local' ? '' : 'none';
  document.getElementById('conn-ssh-fields').style.display   = type==='ssh'   ? '' : 'none';
  if (type === 'ssh') loadSshHistory();
}

// ── SSH History ────────────────────────────────────────────
// 用户切换到 SSH 选项卡时加载历史
async function loadSshHistory() {
  try {
    const r = await fetch('/api/ssh/history');
    const d = await r.json();
    const wrap = document.getElementById('ssh-history-wrap');
    const list = document.getElementById('ssh-hist-list');
    if (!d.history || !d.history.length) { wrap.style.display = 'none'; return; }
    wrap.style.display = '';
    list.innerHTML = '';
    d.history.forEach((h, idx) => {
      const row = document.createElement('div');
      row.className = 'ssh-hist-item';
      const hasPass = h.password ? '🔑' : '';
      row.innerHTML =
        `<span class="sh-label">${esc(h.label||h.username+'@'+h.host)} ${hasPass}</span>` +
        `<span class="sh-addr">${esc(h.username)}@${esc(h.host)}:${h.port||22}</span>` +
        `<span class="sh-del" onclick="event.stopPropagation();deleteSshHistory(${idx})" title="删除">✕</span>`;
      row.addEventListener('click', () => fillSshForm(h));
      list.appendChild(row);
    });
  } catch (e) { console.error('Failed to load SSH history:', e); }
}

// 用户点击 SSH 历史记录项填充表单
function fillSshForm(h) {
  document.getElementById('ssh-label').value = h.label || '';
  document.getElementById('ssh-host').value = h.host || '';
  document.getElementById('ssh-port').value = h.port || 22;
  document.getElementById('ssh-user').value = h.username || '';
  document.getElementById('ssh-pass').value = h.password || '';
  document.getElementById('ssh-key').value = h.key_path || '';
}

// 用户点击删除 SSH 历史记录
async function deleteSshHistory(idx) {
  await fetch(`/api/ssh/history/${idx}`, { method: 'DELETE' });
  loadSshHistory();
}

// ── Add / switch / remove server ───────────────────────────
// 用户添加新的 HTTP 服务器
// 添加新的 HTTP 服务器
async function addServer(host, port, label) {
  const id = `srv${++_srvIdSeq}`;
  const srv = {
    id, label: label || `🤖 ${host}:${port}`,
    host, port: parseInt(port),
    status: 'wait',
    type: 'druidclaw',
    sessions: {},
    activeSession: null,
    terms: {},
  };
  servers.push(srv);
  renderServerBar();
  await switchServer(id);
  return id;
}

// 用户点击服务器标签切换
// 切换服务器
async function switchServer(id) {
  activeSrvId = id;
  _expandedSessionCard = null;  // 清除展开状态
  renderServerBar();
  renderSessionList();
  restoreTerminal();
  renderCards();
  const srv = srvById(id);
  if (!srv || srv.type === 'local' || srv.type === 'ssh') return;
  try {
    const r = await fetch(`${srvBase(srv)}/api/sessions`, { signal: AbortSignal.timeout(3000) });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    srv.status = 'ok';
    renderServerBar();
    renderSessionList();
    renderCards();
  } catch (e) {
    srv.status = 'err';
    renderServerBar();
    toast(`无法连接到 ${srv.label}: ${e.message}`, true);
  }
}

// 用户点击"✕"按钮删除服务器
function removeServer(id) {
  const srv = srvById(id);
  if (!srv) return;
  for (const s of Object.values(srv.sessions)) {
    if (s.ws) s.ws.close();
    if (s.term) s.term.dispose();
  }
  servers = servers.filter(s => s.id !== id);
  if (activeSrvId === id) {
    activeSrvId = servers.length ? servers[servers.length - 1].id : null;
  }
  renderServerBar();
  renderSessionList();
  restoreTerminal();
  saveSessionsToStorage();
}

// 为服务器添加新会话（SSH/本地）
async function addSessionToServer(id) {
  const srv = srvById(id);
  if (!srv) return;

  if (srv.type === 'ssh') {
    // SSH 服务器：使用已保存的参数创建新会话
    const sessName = `ssh_${srv.host}_${Date.now()%10000}`;
    // 从已有会话或存储的参数中获取连接信息
    let params = srv.sessions[Object.keys(srv.sessions)[0]]?.params || {};

    // 如果没有保存的参数，打开模态框让用户输入
    if (!params || !params.username) {
      // 打开 SSH 模态框，预填充 host 和 port
      selectConnType('ssh');
      document.getElementById('srv-modal-title').textContent = 'SSH 连接';
      document.getElementById('srv-modal-ok').textContent = '连接';
      document.getElementById('ssh-label').value = srv.label.replace('🔒 ', '');
      document.getElementById('ssh-host').value = srv.host;
      document.getElementById('ssh-port').value = srv.port || 22;
      document.getElementById('ssh-user').value = '';
      document.getElementById('ssh-pass').value = '';
      document.getElementById('ssh-key').value = '';
      document.getElementById('srv-modal').classList.add('show');
      // 设置临时的 srvEditId，让 commitServer 知道是添加会话而不是新建服务器
      _srvEditId = id;
      return;
    }

    await openSshTerminal(srv, sessName, {
      host: srv.host,
      port: srv.port,
      username: params.username || '',
      password: params.password || '',
      key_path: params.key_path || '',
      label: srv.label,
      save_password: true
    }, srv.id);
  } else if (srv.type === 'local') {
    // 本地终端：直接创建新会话
    const sessName = `local_${Date.now()%10000}`;
    await openLocalTerminal(srv, sessName, '', null);
  }
  saveSessionsToStorage();
}

// ── Server bar render ──────────────────────────────────────
// 渲染服务器栏
function renderServerBar() {
  const bar = document.getElementById('server-bar');
  const addBtn = bar.querySelector('.srv-add');
  bar.innerHTML = '';
  for (const srv of servers) {
    const tab = document.createElement('div');
    tab.className = 'srv-tab' + (srv.id === activeSrvId ? ' active' : '');
    const dotCls = (srv.type === 'local' || srv.type === 'ssh') ? 'dot dot-busy'
                 : srv.status === 'ok'  ? 'dot dot-ok'
                 : srv.status === 'err' ? 'dot dot-err' : 'dot dot-wait';

    // SSH 和本地终端：单击切换服务器
    if (srv.type === 'ssh' || srv.type === 'local') {
      tab.innerHTML =
        `<span class="${dotCls}"></span>` +
        `<span class="lbl" onclick="switchServer('${srv.id}')">${srv.label}</span>` +
        `<span class="x" onclick="event.stopPropagation();removeServer('${srv.id}')">✕</span>`;
    } else {
      tab.innerHTML =
        `<span class="${dotCls}"></span>` +
        `<span class="lbl" onclick="switchServer('${srv.id}')">${srv.label}</span>` +
        `<span class="x" onclick="event.stopPropagation();removeServer('${srv.id}')">✕</span>`;
    }
    bar.appendChild(tab);
  }
  bar.appendChild(addBtn);
}

// ── Add-server modal ───────────────────────────────────────
let _srvEditId = null;

// 关闭服务器模态框
function closeSrvModal(ev) {
  if (ev && ev.target !== document.getElementById('srv-modal')) return;
  document.getElementById('srv-modal').classList.remove('show');
}

// 提交连接表单
async function commitServer() {
  // 如果是为已有 SSH 服务器添加新会话
  if (_srvEditId !== null) {
    const srv = srvById(_srvEditId);
    if (srv && srv.type === 'ssh') {
      const host  = document.getElementById('ssh-host').value.trim();
      const user  = document.getElementById('ssh-user').value.trim();
      const pass  = document.getElementById('ssh-pass').value;
      const key   = document.getElementById('ssh-key').value.trim();
      const label = document.getElementById('ssh-label').value.trim() || `${user}@${host}`;
      const port  = parseInt(document.getElementById('ssh-port').value) || 22;

      if (!host || !user) { toast(t('toast_fill_host_user'), true); return; }

      closeSrvModal();
      const sessName = `ssh_${host}_${Date.now()%10000}`;
      await openSshTerminal(srv, sessName, {
        host, port, username: user, password: pass, key_path: key, label,
        save_password: document.getElementById('ssh-save-pass')?.checked || false
      }, srv.id);
      saveSessionsToStorage();
      _srvEditId = null;
      return;
    }
    _srvEditId = null;
  }

  if (_connType === 'ssh') { await connectSSH(); return; }
  if (_connType === 'local') { await connectLocalShell(); return; }
  const label = document.getElementById('m-label').value.trim();
  const host  = document.getElementById('m-host').value.trim();
  const port  = parseInt(document.getElementById('m-port').value) || 19123;
  if (!host) { toast(t('toast_fill_ip'), true); return; }
  closeSrvModal();
  await addServer(host, port, label || `${host}:${port}`);
}

// ── Session persistence ────────────────────────────────────
// 保存会话到 sessionStorage
function saveSessionsToStorage() {
  try {
    const sessionData = servers.map(srv => ({
      id: srv.id,
      label: srv.label,
      host: srv.host,
      port: srv.port,
      type: srv.type,
      activeSession: srv.activeSession,
      sessions: Object.keys(srv.sessions).map(name => {
        const sess = srv.sessions[name];
        return {
          name, status: sess.status, pid: sess.pid,
          params: sess.params, shell: sess.shell
        };
      })
    }));
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sessionData));
  } catch (e) { console.warn('Failed to save sessions:', e); }
}

// 从 sessionStorage 恢复会话
async function restoreSessionsFromStorage() {
  try {
    const data = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!data) return false;
    const sessionData = JSON.parse(data);
    if (!sessionData || sessionData.length === 0) return false;
    servers = [];
    activeSrvId = null;
    let lastSrv = null;
    for (const srvData of sessionData) {
      const srv = {
        id: srvData.id, label: srvData.label, host: srvData.host,
        port: srvData.port, type: srvData.type || 'druidclaw',
        status: 'ok', sessions: {}, activeSession: srvData.activeSession, terms: {}
      };
      servers.push(srv);
      lastSrv = srv;
      for (const sessData of srvData.sessions) {
        if (sessData.name) {
          srv.sessions[sessData.name] = {
            ws: null, term: null, fitAddon: null,
            status: 'reconnecting', pid: null, lastOutputAt: 0,
            params: sessData.params || {}
          };
          if (sessData.params && sessData.params.host) {
            openSshTerminal(srv, sessData.name, sessData.params || {}, null);
          } else if (srvData.type === 'local') {
            openLocalTerminal(srv, sessData.name, sessData.shell || null, null);
          }
        }
      }
    }
    if (servers.length > 0) {
      activeSrvId = servers[servers.length - 1].id;
      renderServerBar();
      renderSessionList();
      renderCards();
      toast(t('toast_restored') + ` ${servers.length} ` + t('session_list'));
      return true;
    }
  } catch (e) { console.error('Failed to restore sessions:', e); }
  return false;
}
