
// ============================================================
//  Server connections
//  (global state defined in connections.js)
// ============================================================

// 获取服务器的基础 URL（用于 REST 请求）
function srvBase(srv) {
  const isSelf = (srv.host === location.hostname ||
                  (srv.host === 'localhost' && location.hostname === 'localhost') ||
                  srv.host === '0.0.0.0');
  if (isSelf && srv.port === parseInt(location.port || 80)) return '';
  return `http://${srv.host}:${srv.port}`;
}

// 构建 WebSocket 连接 URL
function wsUrl(srv, name) {
  const proto = srv.host.startsWith('https') ? 'wss:' : 'ws:';
  return `${proto}//${srv.host}:${srv.port}/ws/${encodeURIComponent(name)}`;
}

// Override openAddServer to reset type
const _origOpenAddServer = typeof openAddServer !== 'undefined' ? openAddServer : null;
function openAddServer() {
  selectConnType('http');
  document.getElementById('srv-modal-title').textContent = t('add_connection');
  document.getElementById('srv-modal-ok').textContent = t('connect_btn');
  // Clear HTTP fields
  ['m-label','m-host'].forEach(id => { const el=document.getElementById(id); if(el) el.value=''; });
  const mp = document.getElementById('m-port'); if (mp) mp.value='19123';
  // Clear SSH fields
  ['ssh-label','ssh-host','ssh-user','ssh-pass','ssh-key'].forEach(id => {
    const el=document.getElementById(id); if(el) el.value='';
  });
  const sp = document.getElementById('ssh-port'); if(sp) sp.value='22';
  document.getElementById('srv-modal').classList.add('show');
}

// ── Add / switch server ──────────────────────────────────
// Server management functions moved to connections.js

// ── Session persistence ────────────────────────────────────
// Session persistence functions moved to connections.js

// ── Server bar render ────────────────────────────────────
// renderServerBar moved to connections.js

// ── Add-server modal ─────────────────────────────────────
// closeSrvModal and commitServer moved to connections.js

// 获取 xterm.js 终端构造函数（通过 CDN 加载）
function _getTerminalConstructors() {
  return {
    createTerminal: () => new Terminal({
      cursorBlink: true, fontSize: 14, fontFamily: 'monospace',
      theme: _xtermTheme()
    }),
    FitAddon: window.FitAddon,
    WebLinksAddon: window.WebLinksAddon,
  };
}

// ── Server settings (current server config) ─────────────
let _cfgData = {};
function cfgTab(name) {
  ['basic', 'files'].forEach(t => {
    const tabEl = document.getElementById('cfg-tab-' + t);
    const paneEl = document.getElementById('cfg-pane-' + t);
    if (tabEl) tabEl.classList.toggle('active', t === name);
    if (paneEl) paneEl.style.display = t === name ? '' : 'none';
  });
  const closeEl = document.getElementById('cfg-files-close');
  if (closeEl) closeEl.style.display = name === 'files' ? 'flex' : 'none';
}
// 打开服务器配置模态框
async function openSrvSettings() {
  cfgTab('basic');
  try {
    const r = await fetch('/api/config');
    _cfgData = await r.json();
  } catch (e) { _cfgData = { host: '0.0.0.0', port: 19123 }; }
  document.getElementById('c-host').value = _cfgData.host || '0.0.0.0';
  document.getElementById('c-port').value = _cfgData.port || 19123;
  document.getElementById('cfg-modal').classList.add('show');
  setTimeout(() => document.getElementById('c-host').focus(), 50);
}
// 关闭配置模态框
function closeCfgModal(ev) {
  if (ev && ev.target !== document.getElementById('cfg-modal')) return;
  document.getElementById('cfg-modal').classList.remove('show');
}
// 仅保存配置（不重启）
async function saveConfigOnly() {
  const host = document.getElementById('c-host').value.trim();
  const port = parseInt(document.getElementById('c-port').value);
  const r = await fetch('/api/config', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ host, port })
  });
  const d = await r.json();
  if (d.error) { toast('保存失败: ' + d.error, true); return; }
  closeCfgModal();
  toast(`配置已保存 ${host}:${port}（重启后生效）`);
}
// 保存配置并重启服务
async function saveAndRestart() {
  const host = document.getElementById('c-host').value.trim();
  const port = parseInt(document.getElementById('c-port').value);
  const r = await fetch('/api/config', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ host, port })
  });
  const d = await r.json();
  if (d.error) { toast('保存失败: ' + d.error, true); return; }
  closeCfgModal();
  try { await fetch('/api/restart', { method: 'POST' }); } catch (_) {}
  document.getElementById('spin-overlay').classList.add('show');
  const dh = (host === '0.0.0.0' || host === '::') ? location.hostname : host;
  const newOrigin = `${location.protocol}//${dh}:${port}`;
  let n = 0;
  async function poll() {
    n++;
    document.getElementById('spin-msg').textContent = `等待 ${dh}:${port} 上线... (${n}/30)`;
    try {
      const res = await fetch(`${newOrigin}/api/config`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) { location.href = newOrigin; return; }
    } catch (_) {}
    if (n < 30) setTimeout(poll, 1000); else
      document.getElementById('spin-msg').textContent = `超时，请手动访问 ${newOrigin}`;
  }
  setTimeout(poll, 1500);
}

// ============================================================
//  Session management (per server)
// ============================================================
// 刷新会话列表
async function refreshSessions() {
  const srv = activeSrv();
  if (!srv) return;
  try {
    const r = await fetch(`${srvBase(srv)}/api/sessions`);
    const data = await r.json();
    srv.status = 'ok';
    renderServerBar();
    renderSessionList();
  } catch (e) {
    srv.status = 'err';
    renderServerBar();
    toast('刷新失败: ' + e.message, true);
  }
}



// ── Activity dot helpers ─────────────────────────────────
const BUSY_TTL = 1800;  // ms of no output → considered idle

// 获取会话状态点 class（busy/idle/error）
function sessDotClass(s) {
  if (s.status === 'connecting') return 'dot-wait';
  if (s.status === 'dead')       return 'dot-err';
  // alive: busy or idle
  const busy = s.lastOutputAt && (Date.now() - s.lastOutputAt < BUSY_TTL);
  return busy ? 'dot-busy' : 'dot-ok';
}

// 获取会话状态文本
function sessStatusText(s) {
  if (s.status === 'connecting') return t('connecting');
  if (el) {
    el.className = `s-dot ${sessDotClass(s)}`;
  }
  const statusId = `status-${srv.id}-${CSS.escape(name)}`;
  const sel = document.getElementById(statusId);
  if (sel) {
    const dc = sessDotClass(s);
    sel.textContent = sessStatusText(s);
    sel.className = `s-status s-status-${dc}`;
  }
}

// Periodic checker: transition busy → idle after BUSY_TTL
setInterval(() => {
  for (const srv of servers) {
    for (const [name, s] of Object.entries(srv.sessions)) {
      if (s.status === 'alive' && s.lastOutputAt) {
        const wasBusy = Date.now() - s.lastOutputAt < BUSY_TTL + 100;
        const isNowIdle = Date.now() - s.lastOutputAt >= BUSY_TTL;
        if (wasBusy && isNowIdle) updateDot(srv, name);
      }
    }
  }
}, 300);

// ── Session list render ──────────────────────────────────
// 渲染会话列表（侧边栏）
function renderSessionList() {
  const srv = activeSrv();
  const list = document.getElementById('session-list');
  const empty = document.getElementById('sess-empty');
  if (!list || !empty) return;  // sidebar now uses card list; elements may be absent
  list.querySelectorAll('.sess-item').forEach(e => e.remove());
  if (!srv || Object.keys(srv.sessions).length === 0) {
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  for (const [name, s] of Object.entries(srv.sessions)) {
    const item = document.createElement('div');
    item.className = 'sess-item' + (name === srv.activeSession ? ' active' : '');
    item.dataset.name = name;
    const dotCls = sessDotClass(s);
    const dotId = `dot-${srv.id}-${CSS.escape(name)}`;
    const statusId = `status-${srv.id}-${CSS.escape(name)}`;
    item.innerHTML =
      `<span class="s-dot ${dotCls}" id="${dotId}"></span>` +
      `<span class="s-status s-status-${dotCls}" id="${statusId}">${sessStatusText(s)}</span>` +
      `<span class="s-name" title="双击重命名">${name}</span>` +
      `<span class="s-actions">` +
        `<span class="s-btn" title="重命名" data-act="rename">✎</span>` +
        `<span class="s-btn danger" title="${t('kill')}" data-act="kill">✕</span>` +
      `</span>`;
    // click → switch
    item.addEventListener('click', e => {
      if (e.target.dataset.act) return;  // handled below
      const srv2 = activeSrv();
      if (srv2) connectSession(srv2, name);
    });
    // action buttons
    item.querySelector('[data-act="rename"]').addEventListener('click', e => {
      e.stopPropagation(); startRename(item, name);
    });
    item.querySelector('[data-act="kill"]').addEventListener('click', e => {
      e.stopPropagation(); killSession(e, name);
    });
    // double-click on name → rename
    item.querySelector('.s-name').addEventListener('dblclick', e => {
      e.stopPropagation(); startRename(item, name);
    });
    list.appendChild(item);
  }
}

// ── Inline rename ─────────────────────────────────────────
// 开始内联重命名会话
function startRename(item, oldName) {
  // Replace the name span with an input
  const nameSpan = item.querySelector('.s-name');
  const actions  = item.querySelector('.s-actions');
  nameSpan.style.display = 'none';
  actions.style.display  = 'none';

  const input = document.createElement('input');
  input.className = 's-rename-input';
  input.value = oldName;
  item.insertBefore(input, actions);
  input.focus();
  input.select();

  const finish = async (commit) => {
    input.remove();
    nameSpan.style.display = '';
    actions.style.display  = '';
    if (!commit) return;
    const newName = input.value.trim();
    if (!newName || newName === oldName) return;
    await commitRename(oldName, newName);
  };

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); finish(true); }
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    e.stopPropagation();
  });
  input.addEventListener('blur', () => finish(true));
  // Prevent click-outside from triggering session switch
  input.addEventListener('click', e => e.stopPropagation());
}

// 提交重命名（调用 API）
async function commitRename(oldName, newName) {
  const srv = activeSrv();
  if (!srv) return;
  try {
    const r = await fetch(
      `${srvBase(srv)}/api/sessions/${encodeURIComponent(oldName)}`,
      { method: 'PATCH', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ new_name: newName }) }
    );
    const d = await r.json();
    if (!r.ok || d.error || d.detail) {
      toast('重命名失败: ' + (d.error || d.detail || r.status), true); return;
    }
    // Update local state
    const s = srv.sessions[oldName];
    if (s) {
      srv.sessions[newName] = s;
      delete srv.sessions[oldName];
    }
    if (srv.activeSession === oldName) srv.activeSession = newName;
    renderSessionList();
    updateToolbar();
    toast(`已重命名: ${oldName} → ${newName}`);
  } catch (e) {
    toast('重命名失败: ' + e.message, true);
  }
}

// 终止会话
async function killSession(ev, name) {
  ev.stopPropagation();
  const srv = activeSrv();
  if (!srv) return;
  try {
    await fetch(`${srvBase(srv)}/api/sessions/${encodeURIComponent(name)}?force=true`, { method: 'DELETE' });
  } catch (_) {}
  const s = srv.sessions[name];
  if (s) { s.status = 'dead'; renderSessionList(); if (srv.activeSession === name) updateToolbar(); }
}

// ============================================================
//  Terminal & WebSocket
// ============================================================
// 创建终端实例（xterm）
function createTerminal() {
  const term = new Terminal({
    theme: _xtermTheme(),
    fontFamily: '"Cascadia Code","Fira Code",Menlo,monospace',
    fontSize: 14, lineHeight: 1.2, cursorBlink: true,
    scrollback: 5000, allowProposedApi: true,
  });
  const fit = new FitAddon.FitAddon();
  const links = new WebLinksAddon.WebLinksAddon();
  term.loadAddon(fit);
  term.loadAddon(links);
  return { term, fit };
}


// 分离所有终端，附加活动会话到 DOM
function restoreTerminal() {
  const wrap = document.getElementById('term-wrap');
  const empty = document.getElementById('term-empty');
  // Remove all xterm elements
  wrap.querySelectorAll('.xterm').forEach(e => e.remove());

  const srv = activeSrv();
  if (!srv || !srv.activeSession || !srv.sessions[srv.activeSession]) {
    empty.style.display = '';
    hideToolbarItems(); return;
  }
  empty.style.display = 'none';
  const s = srv.sessions[srv.activeSession];
  s.term.open(wrap);
  setTimeout(() => safeFit(srv, srv.activeSession), 40);
  updateToolbar();
  s.term.focus();
}

// 安全地调整终端大小（检查会话是否仍为活动）
function safeFit(srv, name) {
  const s = srv && srv.sessions[name];
  if (!s || srv.id !== activeSrvId || name !== srv.activeSession) return;
  try {
    s.fitAddon.fit();
    const { rows, cols } = s.term;
    if (s.ws && s.ws.readyState === WebSocket.OPEN) {
      s.ws.send(JSON.stringify({ type:'resize', rows, cols }));
    }
  } catch (_) {}
}

// 清空终端内容
function clearTerm() {
  const srv = activeSrv();
  if (srv && srv.activeSession && srv.sessions[srv.activeSession])
    srv.sessions[srv.activeSession].term.clear();
}

// ── Toolbar ──────────────────────────────────────────────
// 隐藏工具栏项
function hideToolbarItems() {
  ['t-name','t-pid','t-badge','t-clear','t-kill'].forEach(id => {
    document.getElementById(id).style.display = 'none';
  });
}
// 更新工具栏显示（会话名、PID、状态）
function updateToolbar() {
  const srv = activeSrv();
  if (!srv || !srv.activeSession) { hideToolbarItems(); return; }
  const name = srv.activeSession;
  const s = srv.sessions[name];
  if (!s) { hideToolbarItems(); return; }
  document.getElementById('t-name').textContent = name;
  document.getElementById('t-name').style.display = '';
  document.getElementById('t-pid').textContent = s.pid ? `pid=${s.pid}` : '';
  document.getElementById('t-pid').style.display = s.pid ? '' : 'none';
  const badge = document.getElementById('t-badge');
  badge.style.display = '';
  badge.className = 'badge ' + (s.status === 'alive' ? 'badge-alive' : s.status === 'connecting' ? 'badge-conn' : 'badge-dead');
  badge.textContent = s.status === 'alive' ? t('status_running') : s.status === 'connecting' ? t('status_connecting') : t('status_stopped');
  document.getElementById('t-clear').style.display = '';
  document.getElementById('t-kill').style.display = '';
}

// ── Sidebar toggle ────────────────────────────────────────
// 切换侧边栏折叠状态
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('collapsed');
  setTimeout(() => {
    const srv = activeSrv();
    if (srv && srv.activeSession) safeFit(srv, srv.activeSession);
  }, 220);
}

// ============================================================
//  Feishu bot panel
// ============================================================
let _feishuPollTimer = null;
let _feishuEventIndex = 0;

// 打开飞书模态框
function openFeishuModal() {
  document.getElementById('feishu-overlay').classList.add('show');
  feishuLoadConfig();
  feishuLoadStatus();
  feishuLoadBridge();
  _startFeishuPoll();
  setTimeout(() => document.getElementById('f-appid').focus(), 50);
}
// 关闭飞书模态框
function closeFeishuModal(ev) {
  if (ev && ev.target !== document.getElementById('feishu-overlay')) return;
  document.getElementById('feishu-overlay').classList.remove('show');
  _stopFeishuPoll();
}

// 加载飞书配置
async function feishuLoadConfig() {
  try {
    const r = await fetch('/api/feishu/config');
    const d = await r.json();
    document.getElementById('f-appid').value = d.app_id || '';
    // Don't pre-fill secret (show placeholder)
    if (d.app_secret) document.getElementById('f-secret').placeholder = '已保存（留空则不修改）';
  } catch (_) {}
}

// 加载飞书状态
async function feishuLoadStatus() {
  try {
    const r = await fetch('/api/feishu/status');
    const d = await r.json();
    _applyFeishuStatus(d);
  } catch (_) {}
}

// 应用飞书状态到 UI
function _applyFeishuStatus(d) {
  const dot   = document.getElementById('feishu-dot');
  const label = document.getElementById('feishu-label');
  const badge = document.getElementById('f-status-badge');
  const detail = document.getElementById('f-status-detail');
  const connectBtn    = document.getElementById('f-connect-btn');
  const disconnectBtn = document.getElementById('f-disconnect-btn');

  const st = d.status || 'disconnected';

  // Header badge
  const colors = { connected:'var(--green)', connecting:'var(--yellow)',
                   error:'var(--red)', disconnected:'var(--muted)' };
  dot.style.background = colors[st] || 'var(--muted)';
  dot.style.animation = st === 'connecting' ? 'pulse .9s infinite alternate' : '';
  label.textContent = st === 'connected' ? `飞书 ✓` :
                      st === 'connecting' ? '飞书 …' :
                      st === 'error' ? '飞书 ✗' : t('feishu');

  // Modal badge
  badge.className = 'badge ' +
    (st === 'connected'   ? 'badge-alive' :
     st === 'connecting'  ? 'badge-conn'  : 'badge-dead');
  badge.textContent = st === 'connected'  ? t('feishu_connected') :
                      st === 'connecting' ? t('feishu_connecting') :
                      st === 'error'      ? t('error')   : t('feishu_disconnected');

  detail.textContent = d.error ? `错误: ${d.error}` :
                       d.connected_at ? `连接时间: ${d.connected_at}` : '';

  const isConn = st === 'connected' || st === 'connecting';
  connectBtn.style.display    = isConn ? 'none' : '';
  disconnectBtn.style.display = isConn ? '' : 'none';
}

// 保存配置并连接飞书 bot
async function feishuSaveAndConnect() {
  const appId  = document.getElementById('f-appid').value.trim();
  const secret = document.getElementById('f-secret').value.trim();

  if (!appId) { toast(t('toast_fill_app_id'), true); return; }

  // Only save if secret was entered
  if (secret) {
    const r = await fetch('/api/feishu/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ app_id: appId, app_secret: secret })
    });
    const d = await r.json();
    if (d.error || d.detail) { toast('保存失败: ' + (d.error || d.detail), true); return; }
    document.getElementById('f-secret').value = '';
    document.getElementById('f-secret').placeholder = '已保存（留空则不修改）';
    toast(t('toast_saved'));
  }

  // Connect
  const r2 = await fetch('/api/feishu/connect', { method: 'POST' });
  const d2 = await r2.json();
  if (d2.error || d2.detail) { toast('连接失败: ' + (d2.error || d2.detail), true); return; }
  toast('飞书 bot 已启动，正在连接...');
  feishuLoadStatus();
}

// 断开飞书连接
async function feishuDisconnect() {
  await fetch('/api/feishu/disconnect', { method: 'POST' });
  toast('飞书 bot 已断开');
  feishuLoadStatus();
}

// ── Bridge config ─────────────────────────────────────────
let _bridgeSaveTimer = null;

// 加载飞书桥接配置
async function feishuLoadBridge() {
  try {
    const r = await fetch('/api/feishu/bridge');
    const d = await r.json();
    document.getElementById('f-bridge-delay').value = d.reply_delay || 4;
  } catch (_) {}
}

// 保存飞书桥接配置（防抖）
function bridgeSave() {
  clearTimeout(_bridgeSaveTimer);
  _bridgeSaveTimer = setTimeout(async () => {
    const payload = {
      reply_delay: parseFloat(document.getElementById('f-bridge-delay').value) || 4,
    };
    try {
      await fetch('/api/feishu/bridge', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
    } catch (_) {}
  }, 600);
}

// Poll for new events while modal is open
// 开始飞书事件轮询
function _startFeishuPoll() {
  _feishuEventIndex = 0;
  _feishuPollTick();
}
// 停止飞书事件轮询
function _stopFeishuPoll() {
  clearTimeout(_feishuPollTimer);
}
// 轮询飞书事件（增量获取）
async function _feishuPollTick() {
  try {
    const [statusR, eventsR] = await Promise.all([
      fetch('/api/feishu/status'),
      fetch(`/api/feishu/events?after=${_feishuEventIndex}`)
    ]);
    const status = await statusR.json();
    const evData = await eventsR.json();
    _applyFeishuStatus(status);
    if (evData.events && evData.events.length > 0) {
      _feishuEventIndex = evData.total;
      _appendFeishuEvents(evData.events);
    }
  } catch (_) {}
  if (document.getElementById('feishu-overlay').classList.contains('show')) {
    _feishuPollTimer = setTimeout(_feishuPollTick, 2000);
  }
}

// 追加飞书事件到日志
function _appendFeishuEvents(events) {
  const log = document.getElementById('f-event-log');
  const empty = log.querySelector('.ev-empty');
  if (empty) empty.remove();

  for (const ev of events) {
    const row = document.createElement('div');
    row.className = 'ev-item';
    row.title = JSON.stringify(ev.raw, null, 2).slice(0, 500);
    row.innerHTML =
      `<span class="ev-time">${ev.time}</span>` +
      `<span class="ev-type">${ev.type}</span>` +
      `<span class="ev-sum">${esc(translateSystemEvent(ev.summary))}</span>`;
    log.appendChild(row);
  }
  log.scrollTop = log.scrollHeight;
}

// ============================================================
//  Card management
// ============================================================

let _cards = [];
let _expandedCardId = null;
let _expandedSessionCard = null;  // 格式：srvId:sessionName
let _ncType = 'claude';
let _cardPollTimer = null;
// _fpEvIdx removed; replaced by _fpEvIdxMap (per-card event index)

// ── Load + render ─────────────────────────────────────────
// 从后端加载卡片列表
async function loadCards() {
  try {
    const r = await fetch('/api/cards');
    const d = await r.json();
    _cards = d.cards || [];
    // 只有在 DruidClaw 服务器类型下才渲染卡片
    const srv = activeSrv();
    if (!srv || srv.type === 'druidclaw') {
      renderCards();
    }
  } catch (_) {}
}

// 渲染卡片列表（根据服务器类型显示不同内容）
function renderCards() {
  const list = document.getElementById('cards-list');
  const hdrTitle = document.querySelector('.cards-hdr-title');
  const addBtn = document.querySelector('.cards-add-btn');
  if (!list) return;

  const srv = activeSrv();
  list.innerHTML = '';

  // 根据服务器类型显示不同的内容
  if (srv && srv.type === 'local') {
    // 本地终端服务器 - 显示会话列表
    if (hdrTitle) hdrTitle.textContent = t('local_terminal');
    if (addBtn) {
      addBtn.onclick = () => addLocalSessionToCurrentServer();
      addBtn.title = t('new_card');
    }
    // 显示当前服务器的会话列表
    const sessions = srv.sessions || {};
    if (!Object.keys(sessions).length) {
      list.innerHTML = `<div class="cards-empty">${t('no_local_terminal')}</div>`;
    } else {
      for (const [name, sess] of Object.entries(sessions)) {
        list.appendChild(buildSessionCardEl(srv, name, sess));
      }
    }
  } else if (srv && srv.type === 'ssh') {
    // SSH 终端服务器 - 显示会话列表
    if (hdrTitle) hdrTitle.textContent = t('ssh_terminal');
    if (addBtn) {
      addBtn.onclick = () => addSshSessionToCurrentServer();
      addBtn.title = t('new_ssh_terminal');
    }
    // 显示当前服务器的会话列表
    const sessions = srv.sessions || {};
    if (!Object.keys(sessions).length) {
      list.innerHTML = `<div class="cards-empty">${t('no_ssh_session')}</div>`;
    } else {
      for (const [name, sess] of Object.entries(sessions)) {
        list.appendChild(buildSessionCardEl(srv, name, sess));
      }
    }
  } else {
    // DruidClaw 服务器 - 显示 Claude 卡片和正在运行的 IM bot 卡片
    if (hdrTitle) hdrTitle.textContent = 'Claude Sessions';
    if (addBtn) {
      addBtn.onclick = openNewCardModal;
      addBtn.title = t('new_card');
    }
    const claude = _cards.filter(c => c.type === 'claude');
    // Also show running IM bots as they have associated Claude sessions
    const runningImBots = _cards.filter(c => _IM_TYPES.includes(c.type) && c.status && c.status.running);
    const allCards = [...claude, ...runningImBots];
    if (!allCards.length) {
      list.innerHTML = `<div class="cards-empty">${t('no_claude_session')}</div>`;
    } else {
      for (const c of allCards) list.appendChild(buildCardEl(c));
    }
  }
  renderFeishuPage();
}

// 构建会话卡片元素（用于终端类型服务器）
function buildSessionCardEl(srv, name, sess) {
  const div = document.createElement('div');
  const isActive = name === srv.activeSession;
  // 使用展开状态跟踪
  const isExp = _expandedSessionCard === `${srv.id}:${name}`;
  div.className = 'card' + (isActive ? ' card-active' : '') + (isExp ? ' expanded' : '');
  div.dataset.sessionName = name;

  const status = sess.status || 'unknown';
  const dotColor = status === 'alive' ? 'var(--green)' :
                   status === 'connecting' || status === 'reconnecting' ? 'var(--yellow)' :
                   status === 'dead' ? 'var(--red)' : 'var(--muted)';
  const icon = srv.type === 'ssh' ? '🔒' : '🖥';
  const statusLabel = status === 'alive' ? t('status_running') :
                      status === 'connecting' || status === 'reconnecting' ? t('status_connecting') :
                      status === 'dead' ? t('status_stopped') : t('unknown');
  // 根据状态显示不同信息
  let metaText;
  if (sess.pid) {
    metaText = `PID: ${sess.pid}`;
  } else if (status === 'reconnecting') {
    metaText = t('status_connecting') + '...';
  } else if (status === 'connecting') {
    metaText = t('status_connecting') + '...';
  } else if (status === 'alive') {
    metaText = t('status_running');
  } else {
    metaText = t('not_connected');
  }

  div.innerHTML = `
    <div class="card-hdr" onclick="toggleSessionCard('${srv.id}', '${escHtmlAttr(name)}')" title="点击展开/折叠，双击重命名">
      <span class="card-icon">${icon}</span>
      <span class="card-name" title="${esc(t('double_click_rename'))}">${esc(name)}</span>
      <span class="card-rename-btn" onclick="event.stopPropagation();startRenameSessionCardBtn(this, '${srv.id}', '${escHtmlAttr(name)}')" title="${esc(t('rename'))}">✏</span>
      <span class="card-dot" style="background:${dotColor}" title="${statusLabel}"></span>
      <span class="card-chevron" onclick="event.stopPropagation();toggleSessionCard('${srv.id}', '${escHtmlAttr(name)}')" title="${esc(t('expand'))}">▲</span>
    </div>
    <div class="card-body">
      <div class="card-meta" style="display:flex;align-items:center;justify-content:space-between">
        <span>${metaText}</span>
        <button class="cbtn del" onclick="killSessionByName('${srv.id}', '${escHtmlAttr(name)}')" title="${esc(t('close'))}">${esc(t('close'))}</button>
      </div>
    </div>
  `;

  // 双击名称重命名
  const nameEl = div.querySelector('.card-name');
  nameEl.addEventListener('dblclick', (e) => {
    e.stopPropagation();
    startRenameSessionCard(nameEl, srv, name);
  });

  return div;
}

// 内联重命名会话卡片（通过按钮触发）
function startRenameSessionCardBtn(btn, srvId, oldName) {
  const srv = srvById(srvId);
  if (srv) startRenameSessionCardSimple(srv, oldName);
}

// 内联重命名会话卡片（从双击调用）
function startRenameSessionCard(nameSpan, srv, oldName) {
  startRenameSessionCardSimple(srv, oldName);
}

// 内联重命名会话卡片
function startRenameSessionCardSimple(srv, oldName) {
  // 找到显示该名称的卡片
  const cardEl = document.querySelector(`.card[data-session-name="${oldName}"]`);
  if (!cardEl) return;

  const nameSpan = cardEl.querySelector('.card-name');
  const renameBtn = cardEl.querySelector('.card-rename-btn');
  const hdr = cardEl.querySelector('.card-hdr');

  const input = document.createElement('input');
  input.className = 'card-name-input';
  input.value = oldName;
  input.style.cssText = 'flex:1;font-size:12px;padding:2px 4px;border:1px solid var(--blue);border-radius:3px;background:var(--bg);color:var(--text);width:100%;';

  // 隐藏名称和重命名按钮，显示输入框
  nameSpan.style.display = 'none';
  if (renameBtn) renameBtn.style.display = 'none';
  hdr.insertBefore(input, nameSpan);
  input.focus();
  input.select();

  const finish = async (commit) => {
    input.remove();
    nameSpan.style.display = '';
    if (renameBtn) renameBtn.style.display = '';
    if (!commit) return;
    const newName = input.value.trim();
    if (!newName || newName === oldName) return;

    // 更新会话键名
    const s = srv.sessions[oldName];
    srv.sessions[newName] = s;
    delete srv.sessions[oldName];
    if (srv.activeSession === oldName) srv.activeSession = newName;

    // 更新 UI 和保存会话
    renderCards();
    renderSessionList();
    saveSessionsToStorage();
    toast(`已重命名：${oldName} → ${newName}`);
  };

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    e.stopPropagation();
  });
  input.addEventListener('blur', () => finish(true));
}

function connectSessionByName(srvId, name) {
  const srv = srvById(srvId);
  if (srv) connectSession(srv, name);
}

function killSessionByName(srvId, name) {
  const srv = srvById(srvId);
  if (!srv || !srv.sessions[name]) return;

  // 检查会话状态，已停止的会话不需要确认
  const s = srv.sessions[name];
  const isAlive = s && s.status === 'alive';
  if (isAlive && !confirm(t('toast_confirm_delete_session'))) return;

  // 关闭 WebSocket 和终端
  if (s.ws) s.ws.close();
  if (s.term) s.term.dispose();

  // 删除会话
  delete srv.sessions[name];
  if (srv.activeSession === name) {
    srv.activeSession = Object.keys(srv.sessions)[0] || null;
  }

  // 如果在终端区域显示的是这个会话，清屏
  if (srv.activeSession === null) {
    document.getElementById('term-empty').style.display = '';
    document.getElementById('t-name').style.display = 'none';
    document.getElementById('t-pid').style.display = 'none';
    document.getElementById('t-clear').style.display = 'none';
    document.getElementById('t-kill').style.display = 'none';
  }

  // 更新 UI 和保存会话
  renderCards();
  renderSessionList();
  updateToolbar();
  saveSessionsToStorage();
}

// 打开 SSH 连接对话框（用于在 SSH 服务器下新建终端）
function openSshConnect() {
  const srv = activeSrv();
  if (!srv) return;
  // 填充 SSH 信息（从当前服务器的会话中获取）
  const firstSess = srv.sessions && Object.values(srv.sessions)[0];
  const params = firstSess?.params || {};
  document.getElementById('ssh-label').value = '';
  document.getElementById('ssh-host').value = params.host || srv.host || '';
  document.getElementById('ssh-port').value = params.port || srv.port || 22;
  document.getElementById('ssh-user').value = params.username || '';
  document.getElementById('ssh-pass').value = params.password || '';
  document.getElementById('ssh-key').value = params.key_path || '';
  selectConnType('ssh');
  document.getElementById('srv-modal-title').textContent = t('new_ssh_terminal');
  document.getElementById('srv-modal-ok').textContent = t('connect_btn');
  document.getElementById('srv-modal').classList.add('show');
}

const _IM_TYPES = ['feishu','telegram','dingtalk','qq','wework'];
const _IM_ICONS = {feishu:'🔔', telegram:'✈️', dingtalk:'📎', qq:'🐧', wework:'💼'};
// Labels are resolved via i18n at render time
function _imLabel(type) {
  const keys = {feishu:'im_feishu', dingtalk:'im_dingtalk', wework:'im_wework'};
  return keys[type] ? t(keys[type]) : type.charAt(0).toUpperCase()+type.slice(1);
}

function _imCredLine(card) {
  if (card.type === 'feishu') {
    const appShort = (card.app_id||'').slice(0,20)+(card.app_id&&card.app_id.length>20?'…':'');
    const secretOk = card.has_secret ? `<span style="color:var(--green)">✓Secret</span>` : `<span style="color:var(--red)">⚠无Secret</span>`;
    return `App: <b>${esc(appShort)}</b> ${secretOk}`;
  } else if (card.type === 'telegram') {
    return card.has_token ? `Token: <span style="color:var(--green)">✓已配置</span>` : `Token: <span style="color:var(--red)">⚠未配置</span>`;
  } else if (card.type === 'dingtalk') {
    const keyShort = (card.app_key||card.app_id||'').slice(0,16)+(card.app_key&&card.app_key.length>16?'…':'');
    const secretOk = card.has_secret ? `<span style="color:var(--green)">✓Secret</span>` : `<span style="color:var(--red)">⚠无Secret</span>`;
    return `Key: <b>${esc(keyShort)}</b> ${secretOk}`;
  } else if (card.type === 'qq') {
    return `WS: <b>${esc((card.ws_url||'').slice(0,30))}</b>`;
  } else if (card.type === 'wework') {
    const corpShort = (card.corp_id||'').slice(0,18);
    const secretSaved = card.has_secret || card.corp_secret ? `<span style="color:var(--green)">✓Secret</span>` : `<span style="color:var(--red)">⚠无Secret</span>`;
    return `Corp: <b>${esc(corpShort)}</b> Agent: <b>${esc(card.agent_id||'')}</b> ${secretSaved}`;
  }
  return '';
}

function _imSessPrefix(card) {
  const prefixes = {feishu:'fbs_', telegram:'tgb_', dingtalk:'dtb_', qq:'qqb_', wework:'wwb_'};
  return (prefixes[card.type]||'bot_') + (card.id||'').slice(0,6);
}

function renderFeishuPage() {
  const list = document.getElementById('fb-card-list');
  if (!list) return;
  const bots = _cards.filter(c => _IM_TYPES.includes(c.type));
  if (!bots.length) {
    list.innerHTML = `<div class="cards-empty">${t('no_im_bots')}</div>`;
    return;
  }
  list.innerHTML = '';
  for (const card of bots) {
    const st = card.status || {};
    const run = st.running;
    const stColor = {connected:'var(--green)',connecting:'var(--yellow)',error:'var(--red)'}[st.status]||'var(--muted)';
    const dotAnim = st.status==='connecting' ? 'animation:pulse .9s infinite alternate' : '';
    const icon = _IM_ICONS[card.type] || '🤖';
    const typeLabel = _imLabel(card.type);

    const btns = run
      ? `<button class="cbtn stp" onclick="cardStop('${card.id}')">${esc(t('stop'))}</button>`
      : `<button class="cbtn ok"  onclick="cardStart('${card.id}')">${esc(t('start'))}</button>`;

    const div = document.createElement('div');
    div.className = 'fb-bot-card' + (run ? ' fb-running' : '');
    div.dataset.id = card.id;
    div.innerHTML = `
      <div class="fb-bot-hdr">
        <span style="width:9px;height:9px;border-radius:50%;background:${stColor};${dotAnim};flex-shrink:0;display:inline-block"></span>
        <span class="fb-bot-name">${icon} ${esc(card.name)}</span>
        <span class="badge ${run ? (st.status==='connected'?'badge-alive':'badge-conn') : 'badge-dead'}">${st.label||'未启动'}</span>
        <span style="margin-left:auto;font-size:10px;color:var(--muted)">${typeLabel}</span>
      </div>
      <div class="fb-bot-meta">
        <span>${_imCredLine(card)}</span>
        ${card.type==='wework' ? `<span>Webhook: <b>/webhook/wecom/${esc(card.id)}</b></span>` : ''}
        <span>Claude Session: <b>${esc(_imSessPrefix(card))}</b></span>
        <span>回复延迟: <b>${card.reply_delay||4}s</b></span>
      </div>
      <div class="fb-bot-actions">
        ${btns}
        <button class="cbtn del" onclick="cardDelete('${card.id}')">${esc(t('delete'))}</button>
      </div>
      <div class="fb-log" id="fblog-${card.id}"><div class="li" style="color:var(--muted)">${run ? esc(t('waiting_events')) : esc(t('not_running'))}</div></div>
    `;
    list.appendChild(div);
  }
}

// ── Page tab switching ─────────────────────────────────────
let _activeTab = 'cc';
function switchTab(mode) {
  _activeTab = mode;
  const sidebar     = document.getElementById('sidebar');
  const termArea    = document.querySelector('.term-area');
  const feishuPage  = document.getElementById('feishu-page');
  const historyPage = document.getElementById('history-page');
  const tabCC       = document.getElementById('tab-cc');
  const tabFeishu   = document.getElementById('tab-feishu');
  const tabHistory  = document.getElementById('tab-history');

  // Hide all non-CC areas first
  if (sidebar)     sidebar.style.display    = 'none';
  if (termArea)    termArea.style.display   = 'none';
  if (feishuPage)  feishuPage.classList.remove('visible');
  if (historyPage) historyPage.classList.remove('visible');
  [tabCC, tabFeishu, tabHistory].forEach(t => t && t.classList.remove('active'));

  if (mode === 'cc') {
    if (sidebar)  sidebar.style.display  = '';
    if (termArea) termArea.style.display = '';
    tabCC.classList.add('active');
    renderCards();  // 根据当前服务器类型渲染卡片
  } else if (mode === 'feishu') {
    if (feishuPage) feishuPage.classList.add('visible');
    tabFeishu.classList.add('active');
    renderFeishuPage();
  } else if (mode === 'history') {
    if (historyPage) historyPage.classList.add('visible');
    if (tabHistory) tabHistory.classList.add('active');
    histLoad();
  }
}

// ── IM config modal ───────────────────────────────────────
let _imType = 'feishu';

function openNewFeishuCardModal() {
  _imType = 'feishu';
  // Reset all form fields
  ['im-fname','im-appid','im-secret','im-delay',
   'im-tg-name','im-tg-token','im-tg-delay',
   'im-dt-name','im-dt-key','im-dt-secret','im-dt-delay',
   'im-qq-name','im-qq-ws','im-qq-token','im-qq-delay',
   'im-ww-name','im-ww-corpid','im-ww-agentid','im-ww-secret',
   'im-ww-token','im-ww-aeskey','im-ww-delay'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.type === 'number' ? (el.value = '4') : (el.value = '');
  });
  document.getElementById('im-autostart').checked = true;
  selectImType('feishu');
  document.getElementById('new-im-modal').classList.add('show');
}

function closeNewImModal(ev) {
  if (ev && ev.target !== document.getElementById('new-im-modal')) return;
  document.getElementById('new-im-modal').classList.remove('show');
}

function selectImType(type) {
  _imType = type;
  ['feishu','telegram','dingtalk','qq','wework'].forEach(t => {
    const btn = document.getElementById(`im-t-${t}`);
    const frm = document.getElementById(`im-${t}-f`);
    if (btn) btn.classList.toggle('sel', t === type);
    if (frm) frm.style.display = t === type ? '' : 'none';
  });
}

async function submitNewImCard() {
  const autoStart = document.getElementById('im-autostart').checked;
  let body = { type: _imType, auto_start: autoStart };

  if (_imType === 'feishu') {
    const name   = document.getElementById('im-fname').value.trim() || '飞书Bot';
    const appId  = document.getElementById('im-appid').value.trim();
    const secret = document.getElementById('im-secret').value.trim();
    const delay  = parseFloat(document.getElementById('im-delay').value) || 4;
    if (!appId)  { toast(t('toast_fill_app_id'), true); return; }
    if (!secret) { toast(t('toast_fill_secret'), true); return; }
    body = {...body, name, app_id: appId, app_secret: secret, reply_delay: delay};

  } else if (_imType === 'telegram') {
    const name  = document.getElementById('im-tg-name').value.trim() || 'TelegramBot';
    const token = document.getElementById('im-tg-token').value.trim();
    const delay = parseFloat(document.getElementById('im-tg-delay').value) || 4;
    if (!token) { toast(t('toast_fill_token'), true); return; }
    body = {...body, name, token, reply_delay: delay};

  } else if (_imType === 'dingtalk') {
    const name   = document.getElementById('im-dt-name').value.trim() || '钉钉Bot';
    const appKey = document.getElementById('im-dt-key').value.trim();
    const secret = document.getElementById('im-dt-secret').value.trim();
    const delay  = parseFloat(document.getElementById('im-dt-delay').value) || 4;
    if (!appKey) { toast(t('toast_fill_app_key'), true); return; }
    if (!secret) { toast(t('toast_fill_secret'), true); return; }
    body = {...body, name, app_key: appKey, app_secret: secret, reply_delay: delay};

  } else if (_imType === 'qq') {
    const name   = document.getElementById('im-qq-name').value.trim() || 'QQ Bot';
    const wsUrl  = document.getElementById('im-qq-ws').value.trim();
    const token  = document.getElementById('im-qq-token').value.trim();
    const delay  = parseFloat(document.getElementById('im-qq-delay').value) || 4;
    if (!wsUrl) { toast(t('toast_fill_ws_url'), true); return; }
    body = {...body, name, ws_url: wsUrl, access_token: token, reply_delay: delay};

  } else if (_imType === 'wework') {
    const name    = document.getElementById('im-ww-name').value.trim() || '企微Bot';
    const corpId  = document.getElementById('im-ww-corpid').value.trim();
    const agentId = document.getElementById('im-ww-agentid').value.trim();
    const secret  = document.getElementById('im-ww-secret').value.trim();
    const token   = document.getElementById('im-ww-token').value.trim();
    const aesKey  = document.getElementById('im-ww-aeskey').value.trim();
    const delay   = parseFloat(document.getElementById('im-ww-delay').value) || 4;
    if (!corpId)  { toast(t('toast_fill_corp_id'), true); return; }
    if (!agentId) { toast(t('toast_fill_agent_id'), true); return; }
    if (!secret)  { toast('请填写 Corp Secret', true); return; }
    body = {...body, name, corp_id: corpId, agent_id: agentId, corp_secret: secret,
             wework_token: token, encoding_aes_key: aesKey, reply_delay: delay};

  } else {
    toast(t('toast_unknown_type'), true); return;
  }

  try {
    const r = await fetch('/api/cards', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '创建失败');
    document.getElementById('new-im-modal').classList.remove('show');
    toast('IM配置已创建');
    await loadCards();
  } catch (e) { toast(e.message, true); }
}

// 构建 Claude/IM bot 卡片元素
function buildCardEl(card) {
  const st     = card.status || {};
  const run    = st.running;
  const ctype  = card.type;
  const icon   = _IM_ICONS[ctype] || '⚡';
  const label  = st.label || (run ? '运行中' : '未启动');
  const dotCol = _IM_TYPES.includes(ctype)
    ? ({connected:'var(--green)',connecting:'var(--yellow)',error:'var(--red)'}[st.status]||'var(--muted)')
    : (run ? 'var(--green)' : 'var(--muted)');
  const dotAnim = st.status === 'connecting' ? 'animation:pulse .9s infinite alternate' : '';

  const srv = activeSrv();
  const isActive = ctype === 'claude' && srv && srv.activeSession === card.name;
  // Active card or expanded card shows body; active running claude is always expanded
  const isExp = _expandedCardId === card.id || isActive;

  const el = document.createElement('div');
  el.className = 'card'
    + (isExp   ? ' expanded'    : '')
    + (isActive? ' card-active' : '')
    + (run     ? ' card-running': '');
  el.dataset.id = card.id;

  el.innerHTML = `
    <div class="card-hdr" onclick="cardSwitch('${card.id}')" title="${ctype==='claude'&&run?'点击切换终端':'点击展开配置'}">
      <span class="card-icon">${icon}</span>
      <span class="card-name" title="${esc(card.name)}">${esc(card.name)}</span>
      <span class="card-rename-btn" onclick="event.stopPropagation();startRenameCardById('${card.id}')" title="重命名">✏</span>
      <span class="card-dot" style="background:${dotCol};${dotAnim}" title="${label}"></span>
      <span class="card-chevron" onclick="event.stopPropagation();toggleCard('${card.id}')" title="展开/折叠">▲</span>
    </div>
    <div class="card-body">${buildCardBody(card, st)}</div>
  `;
  return el;
}

function buildCardBody(card, st) {
  const run   = st.running;
  const ctype = card.type;

  if (ctype === 'claude') {
    const meta = [
      `<span class="val">${esc(card.workdir||'.')}</span>`,
      card.args && card.args.length ? `参数: <span class="val">${esc(card.args.join(' '))}</span>` : '',
      run ? `PID: <span class="val">${st.pid}</span>` : `<span style="color:var(--red)">${esc(t('stopped'))}</span>`,
    ].filter(Boolean).join('  ');

    // Only delete + stats buttons
    return `<div class="card-meta">${meta}</div>
      <div class="card-actions" style="align-items:center">
        ${run ? `<button class="card-stat-btn" onclick="event.stopPropagation();openStatsModal('${esc(card.name)}')">${esc(t('stats'))}</button>` : ''}
        <button class="cbtn del" onclick="cardDelete('${card.id}')">${esc(t('delete'))}</button>
      </div>`;
  }

  if (['feishu','telegram','dingtalk','qq','wework'].includes(ctype)) {
    const stColor = {connected:'var(--green)',connecting:'var(--yellow)',error:'var(--red)'}[st.status]||'var(--muted)';
    let credLine = '';
    if (ctype === 'feishu') {
      const appShort = (card.app_id||'').slice(0,14)+(card.app_id&&card.app_id.length>14?'…':'');
      const secretSaved = card.has_secret ? `<span style="color:var(--green)">✓已保存</span>` : `<span style="color:var(--red)">未配置</span>`;
      credLine = `App: <span class="val">${esc(appShort)}</span>  Secret: ${secretSaved}`;
    } else if (ctype === 'telegram') {
      credLine = card.has_token ? `Token: <span style="color:var(--green)">✓已保存</span>` : `Token: <span style="color:var(--red)">未配置</span>`;
    } else if (ctype === 'dingtalk') {
      const keyShort = (card.app_key||card.app_id||'').slice(0,14);
      const secretSaved = card.has_secret ? `<span style="color:var(--green)">✓已保存</span>` : `<span style="color:var(--red)">未配置</span>`;
      credLine = `Key: <span class="val">${esc(keyShort)}</span>  Secret: ${secretSaved}`;
    } else if (ctype === 'qq') {
      credLine = `WS: <span class="val">${esc((card.ws_url||'').slice(0,30))}</span>`;
    }
    const meta = [
      credLine,
      `延迟: <span class="val">${card.reply_delay||4}s</span>`,
      run ? `状态: <span class="val" style="color:${stColor}">${st.label}</span>` : '',
    ].filter(Boolean).join('  ');

    const btns = run
      ? `<button class="cbtn stp" onclick="cardStop('${card.id}')">${esc(t('stop'))}</button>
         <button class="cbtn del" onclick="cardDelete('${card.id}')">${esc(t('delete'))}</button>`
      : `<button class="cbtn ok"  onclick="cardStart('${card.id}')">${esc(t('start'))}</button>
         <button class="cbtn del" onclick="cardDelete('${card.id}')">${esc(t('delete'))}</button>`;

    const log = run
      ? `<div class="card-log" id="clog-${card.id}"><div class="li" style="color:var(--muted)">${esc(t('waiting_events'))}</div></div>`
      : '';
    return `<div class="card-meta">${meta}</div><div class="card-actions">${btns}</div>${log}`;
  }
  return '';
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Escape for HTML attribute values (used in onclick handlers)
function escHtmlAttr(s) {
  return String(s||'').replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

// ── Inline rename ─────────────────────────────────────────
function startRenameCardById(id) {
  // Find the card element and trigger rename on its .card-name span
  const cardEl = document.querySelector(`.card[data-id="${id}"]`);
  if (!cardEl) return;
  const nameEl = cardEl.querySelector('.card-name');
  if (nameEl) startRenameCard(id, nameEl);
}

function startRenameCard(id, nameEl) {
  const card = _cards.find(c => c.id === id);
  if (!card) return;
  const inp = document.createElement('input');
  inp.className  = 'card-name-input';
  inp.value      = card.name;
  inp.maxLength  = 40;
  nameEl.replaceWith(inp);
  inp.select();

  const commit = async () => {
    const newName = inp.value.trim();
    if (!newName || newName === card.name) { await loadCards(); return; }
    try {
      const r = await fetch(`/api/cards/${id}`, {
        method: 'PATCH', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ name: newName })
      });
      const d = await r.json();
      if (d.detail || d.error) { toast('重命名失败: '+(d.detail||d.error), true); }
      else toast(`已重命名为 "${newName}"`);
    } catch (e) { toast('重命名失败: '+e.message, true); }
    await loadCards();
  };

  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); commit(); }
    if (e.key === 'Escape') { loadCards(); }
  });
  inp.addEventListener('blur', commit);
  inp.focus();
}

// ── Card actions ──────────────────────────────────────────

// 点击卡片：切换终端或飞书视图
function cardSwitch(id) {
  const card = _cards.find(c => c.id === id);
  if (!card) return;

  if (_IM_TYPES.includes(card.type)) {
    // IM bot card - connect to its Claude session if running
    if (card.status && card.status.running) {
      hideFeishuView();
      const srv = activeSrv();
      if (srv) connectSession(srv, card.name);
      _expandedCardId = id;
      renderCards();
    } else {
      toggleCard(id);
    }
    return;
  }

  // Claude card
  hideFeishuView();
  if (card.status && card.status.running) {
    const srv = activeSrv();
    if (srv) connectSession(srv, card.name);
    _expandedCardId = id;
    renderCards();
  } else {
    toggleCard(id);
  }
}

// 切换卡片展开/折叠状态
function toggleCard(id) {
  _expandedCardId = (_expandedCardId === id) ? null : id;
  renderCards();
}

// 切换会话卡片展开/折叠（本地/SSH 终端）
async function toggleSessionCard(srvId, name) {
  const cardKey = `${srvId}:${name}`;
  const srv = srvById(srvId);
  if (!srv) return;

  // 如果卡片已展开，则折叠
  if (_expandedSessionCard === cardKey) {
    _expandedSessionCard = null;
    renderCards();
    return;
  }

  // 展开卡片并连接会话
  _expandedSessionCard = cardKey;

  // 检查会话是否需要连接
  const sess = srv.sessions[name];
  if (sess && (!sess.ws || sess.ws.readyState !== WebSocket.OPEN)) {
    // 需要连接 - 先隐藏飞书视图，显示终端区域
    hideFeishuView();
    // 确保终端区域显示
    document.getElementById('feishu-view').style.display = 'none';
    document.getElementById('term-wrap').style.display = '';
    // 创建终端连接
    if (srv.type === 'ssh') {
      await openSshTerminal(srv, name, sess.params || {}, srv.id);
    } else if (srv.type === 'local') {
      await openLocalTerminal(srv, name, sess.shell || '', srv.id);
    }
  } else if (sess && sess.ws && sess.ws.readyState === WebSocket.OPEN) {
    // 已连接，直接显示终端
    hideFeishuView();
    document.getElementById('feishu-view').style.display = 'none';
    document.getElementById('term-wrap').style.display = '';
  }

  // 切换到该会话
  srv.activeSession = name;
  activeSrvId = srv.id;

  renderCards();
  renderSessionList();
  restoreTerminal();
  updateToolbar();
}

// 启动卡片
async function cardStart(id) {
  try {
    const r = await fetch(`/api/cards/${id}/start`, {method:'POST'});
    const d = await r.json();
    if (d.detail || d.error) { toast('启动失败: '+(d.detail||d.error), true); return; }
    const card = _cards.find(c=>c.id===id);
    toast(`${card ? card.name : id} 已启动`);
    await loadCards();
    const updated = _cards.find(c=>c.id===id);
    if (updated) {
      _expandedCardId = id;
      if (updated.type === 'claude') {
        hideFeishuView();
        const srv = activeSrv();
        if (srv) connectSession(srv, updated.name);
      } else if (updated.type === 'feishu') {
        showFeishuView(updated);
      }
      renderCards();
    }
  } catch (e) { toast('启动失败: '+e.message, true); }
}

// 停止卡片
async function cardStop(id) {
  try {
    await fetch(`/api/cards/${id}/stop`, {method:'POST'});
    const card = _cards.find(c=>c.id===id);
    toast(`${card ? card.name : id} 已停止`);
    if (_expandedCardId === id) _expandedCardId = null;
    await loadCards();
    if (card && _IM_TYPES.includes(card.type)) renderFeishuPage();
  } catch (e) { toast('停止失败: '+e.message, true); }
}

// 连接到卡片对应的 Claude 会话
async function cardConnect(id) {
  const card = _cards.find(c=>c.id===id);
  if (!card || card.type !== 'claude') return;
  const srv = activeSrv();
  if (!srv) { toast(t('toast_select_server'), true); return; }
  connectSession(srv, card.name);
}

// 删除卡片
async function cardDelete(id) {
  const card = _cards.find(c => c.id === id);
  const isRunning = card && card.status && card.status.running;
  if (isRunning && !confirm(t('toast_confirm_delete_card'))) return;
  try {
    await fetch(`/api/cards/${id}`, {method:'DELETE'});
    if (_expandedCardId === id) _expandedCardId = null;
    toast(t('toast_deleted'));
    await loadCards();
  } catch (e) { toast('删除失败: '+e.message, true); }
}

// ── New-card modal ────────────────────────────────────────
// 打开新建卡片模态框
function openNewCardModal() {
  document.getElementById('new-card-modal').classList.add('show');
  selectNcType('claude');
  // reset fields
  ['nc-name','nc-workdir','nc-args','nc-fname','nc-appid','nc-secret'].forEach(id=>{
    const el = document.getElementById(id);
    if (el) { el.value = id==='nc-workdir'?'.':''; el.placeholder = el.placeholder||''; }
  });
  const dEl = document.getElementById('nc-delay'); if (dEl) dEl.value = '4';
  const asEl = document.getElementById('nc-autostart'); if (asEl) asEl.checked = true;
  setTimeout(()=>document.getElementById('nc-name').focus(), 50);
}

// 关闭新建卡片模态框
function closeNewCardModal(ev) {
  if (ev && ev.target !== document.getElementById('new-card-modal')) return;
  document.getElementById('new-card-modal').classList.remove('show');
}

// 选择新建卡片类型（Claude/Feishu）
function selectNcType(type) {
  _ncType = type;
  document.getElementById('nc-t-claude').classList.toggle('sel', type==='claude');
  const fBtn = document.getElementById('nc-t-feishu');
  if (fBtn) fBtn.classList.toggle('sel', type==='feishu');
  document.getElementById('nc-claude-f').style.display = type==='claude' ? '' : 'none';
  document.getElementById('nc-feishu-f').style.display = type==='feishu' ? '' : 'none';
}

// 提交新建卡片表单
async function submitNewCard() {
  const autoStart = document.getElementById('nc-autostart').checked;
  let payload;
  if (_ncType === 'claude') {
    const name = document.getElementById('nc-name').value.trim();
    const workdir = document.getElementById('nc-workdir').value.trim() || '.';
    const argsRaw = document.getElementById('nc-args').value.trim();
    payload = { type:'claude', name, workdir,
                args: argsRaw ? argsRaw.split(/\s+/) : [],
                auto_start: autoStart };
  } else {
    const appId  = document.getElementById('nc-appid').value.trim();
    const secret = document.getElementById('nc-secret').value.trim();
    if (!appId || !secret) { toast('请填写 App ID 和 App Secret', true); return; }
    payload = { type:'feishu',
                name:       document.getElementById('nc-fname').value.trim() || '飞书Bot',
                app_id:     appId,
                app_secret: secret,
                reply_delay: parseFloat(document.getElementById('nc-delay').value)||4,
                auto_start: autoStart };
  }
  try {
    const r = await fetch('/api/cards', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (d.detail || d.error) { toast('创建失败: '+(d.detail||d.error), true); return; }
    document.getElementById('new-card-modal').classList.remove('show');
    toast(`卡片 "${d.name}" 已创建${autoStart?' 并启动':''}`);
    await loadCards();
    if (autoStart && _ncType === 'claude') {
      const srv = activeSrv();
      if (srv) connectSession(srv, d.name);
    }
  } catch (e) { toast('创建失败: '+e.message, true); }
}

// ── Feishu view (right-side panel) ───────────────────────
let _fvCardId   = null;   // currently shown feishu card id
let _fvPollTimer = null;
let _fvEvIdx    = 0;

// 显示飞书视图（右侧面板）
function showFeishuView(card) {
  _fvCardId = card.id;
  document.getElementById('term-wrap').style.display   = 'none';
  document.getElementById('feishu-view').style.display = '';
  // Update toolbar
  const st = card.status || {};
  document.getElementById('t-name').textContent  = card.name;
  document.getElementById('t-name').style.display = '';
  document.getElementById('t-pid').textContent   = '';
  document.getElementById('t-pid').style.display  = 'none';
  const badge = document.getElementById('t-badge');
  const stMap = {connected:'badge-alive', connecting:'badge-conn', error:'badge-dead', disconnected:'badge-dead'};
  const lblMap = {connected:t('feishu_connected'), connecting:t('feishu_connecting'), error:t('error'), disconnected:t('feishu_disconnected')};
  badge.className = 'badge ' + (stMap[st.status] || 'badge-dead');
  badge.textContent = lblMap[st.status] || t('feishu_disconnected');
  badge.style.display = '';
  const clearBtn = document.getElementById('t-clear');
  clearBtn.textContent = t('clear_log');
  clearBtn.style.display = '';
  clearBtn.onclick = () => {
    document.getElementById('fv-log').innerHTML =
      '<div class="fv-empty"><span>🔔</span><span>' + t('log_cleared') + '</span></div>';
    _fvEvIdx = 0;
  };
  const killBtn = document.getElementById('t-kill');
  killBtn.textContent = t('stop');
  killBtn.style.display = '';
  killBtn.onclick = () => cardStop(_fvCardId);
  // Start polling
  _fvEvIdx = 0;
  clearTimeout(_fvPollTimer);
  _fvPollTick();
}

// 隐藏飞书视图，显示终端
function hideFeishuView() {
  if (!_fvCardId) return;
  _fvCardId = null;
  clearTimeout(_fvPollTimer);
  document.getElementById('feishu-view').style.display = 'none';
  document.getElementById('term-wrap').style.display   = '';
  // Restore kill button behavior
  const killBtn = document.getElementById('t-kill');
  killBtn.textContent = t('kill');
  killBtn.onclick = killActive;
}

// 飞书视图事件轮询
async function _fvPollTick() {
  if (!_fvCardId) return;
  try {
    const [sr, er] = await Promise.all([
      fetch(`/api/feishu/status?card_id=${encodeURIComponent(_fvCardId)}`),
      fetch(`/api/feishu/events?after=${_fvEvIdx}&card_id=${encodeURIComponent(_fvCardId)}`)
    ]);
    const stat = await sr.json();
    const evs  = await er.json();
    // Update toolbar badge
    const card = _cards.find(c => c.id === _fvCardId);
    if (card) {
      const stMap = {connected:'badge-alive', connecting:'badge-conn', error:'badge-dead', disconnected:'badge-dead'};
      const lblMap = {connected:t('feishu_connected'), connecting:t('feishu_connecting'), error:t('error'), disconnected:t('feishu_disconnected')};
      const badge = document.getElementById('t-badge');
      badge.className = 'badge ' + (stMap[stat.status] || 'badge-dead');
      badge.textContent = lblMap[stat.status] || t('feishu_disconnected');
    }
    if (evs.events && evs.events.length) {
      _fvEvIdx = evs.total;
      _fvAppendEvents(evs.events);
    }
  } catch (_) {}
  _fvPollTimer = setTimeout(_fvPollTick, 2000);
}

// 追加事件到飞书视图日志
function _fvAppendEvents(events) {
  const log = document.getElementById('fv-log');
  if (!log) return;
  // Remove placeholder
  log.querySelectorAll('.fv-empty').forEach(e => e.remove());
  for (const ev of events) {
    const row = document.createElement('div');
    row.className = 'fv-item';
    const etype = ev.type || '';
    let badgeCls = 'fv-sys', badgeLbl = t('sys_badge');
    if (etype === 'im.message.receive_v1') { badgeCls = 'fv-in';  badgeLbl = t('user_badge'); }
    else if (etype === 'reply.sent')        { badgeCls = 'fv-out'; badgeLbl = t('claude_badge'); }
    else if (etype.startsWith('system.error') || ev.summary?.startsWith('连接失败'))
                                            { badgeCls = 'fv-err'; badgeLbl = t('error_badge'); }
    row.innerHTML =
      `<span class="fv-time">${ev.time}</span>` +
      `<span class="fv-badge ${badgeCls}">${badgeLbl}</span>` +
      `<span class="fv-content">${esc(translateSystemEvent(ev.summary))}</span>`;
    log.appendChild(row);
  }
  log.scrollTop = log.scrollHeight;
}

// ── Card polling ──────────────────────────────────────────
function startCardPoll() {
  clearTimeout(_cardPollTimer);
  _cardPollTick();
}
// 卡片状态轮询
async function _cardPollTick() {
  await loadCards();
  // Update IM event logs for all running IM bot cards
  for (const card of _cards.filter(c => _IM_TYPES.includes(c.type) && c.status && c.status.running)) {
    try {
      const idx = (_fpEvIdxMap[card.id] || 0);
      // Use generic endpoint for all IM types
      const r = await fetch(`/api/im/${encodeURIComponent(card.id)}/events?after=${idx}`);
      const ev = await r.json();
      if (ev.events && ev.events.length) {
        _fpEvIdxMap[card.id] = ev.total;
        _updateCardLog(card.id, ev.events);
      }
    } catch (_) {}
  }
  _cardPollTimer = setTimeout(_cardPollTick, 4000);
}
let _fpEvIdxMap = {};   // card_id → last event index
// 更新卡片日志（飞书页面或内联日志）
function _updateCardLog(cardId, events) {
  // Feishu page log (fblog-) takes priority; fall back to inline card log (clog-)
  const log = document.getElementById(`fblog-${cardId}`) || document.getElementById(`clog-${cardId}`);
  if (!log) return;
  log.querySelectorAll('.li').forEach(e => { if (e.style.color) e.remove(); });
  for (const ev of events) {
    const row = document.createElement('div');
    row.className = 'li';
    row.title = ev.summary;
    row.innerHTML = `<span style="color:var(--muted);flex-shrink:0">${ev.time}</span>`
      + `<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)">${esc(translateSystemEvent(ev.summary))}</span>`;
    log.appendChild(row);
  }
  while (log.children.length > 30) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}

// Shim: keep old feishu header badge working
function _fpApplyStatus(d) {
  const st = d.status || 'disconnected';
  const col = {connected:'var(--green)',connecting:'var(--yellow)',error:'var(--red)',disconnected:'var(--muted)'}[st]||'var(--muted)';
  const dot = document.getElementById('feishu-dot');
  const lbl = document.getElementById('feishu-label');
  if (dot) dot.style.background = col;
  if (lbl) lbl.textContent = st==='connected'?'飞书 ✓':st==='connecting'?'飞书 …':st==='error'?'飞书 ✗':'飞书';
  _applyFeishuStatus(d);
}
function sbFeishuLoadStatus() {
  fetch('/api/feishu/status').then(r=>r.json()).then(_fpApplyStatus).catch(()=>{});
}
function _sbApplyStatus(d) { _fpApplyStatus(d); }

// ── Skills Marketplace ────────────────────────────────────
let _mktPlugins = [];
let _mktInstalled = new Set();
let _mktName = '';
let _mktSources = [];
let _mktBusy = false;

async function openMarketplace() {
  document.getElementById('mkt-overlay').classList.add('show');
  // Load default marketplace sources from backend
  try {
    const r = await fetch('/api/marketplace/list');
    const d = await r.json();
    _mktSources = d.marketplaces || [];
    _renderMktTabs();
    // Auto-load first source
    if (_mktSources.length > 0) {
      mktLoadSource(_mktSources[0]);
    }
  } catch (e) {
    mktStatus('加载市场列表失败: ' + e.message, true);
  }
}

function closeMkt(ev) {
  if (ev && ev.target !== document.getElementById('mkt-overlay')) return;
  document.getElementById('mkt-overlay').classList.remove('show');
}

function _renderMktTabs() {
  const tabs = document.getElementById('mkt-src-tabs');
  tabs.innerHTML = _mktSources.map((s, i) =>
    `<div class="mkt-src-tab${i===0?' active':''}" id="mkt-tab-${i}"
      onclick="mktLoadSource(_mktSources[${i}],${i})">${s.label}</div>`
  ).join('') + `<div class="mkt-src-tab" onclick="mktLoadSource(null,-1)">+ 自定义</div>`;
}

async function mktLoadSource(src, idx) {
  // Update tab active state
  document.querySelectorAll('.mkt-src-tab').forEach((t, i) => {
    t.classList.toggle('active', i === idx);
  });
  if (!src) {
    // Custom URL mode: just focus the URL input
    document.getElementById('mkt-url').focus();
    return;
  }
  document.getElementById('mkt-url').value = src.url;
  await _mktFetch(src.url, src.name);
}

async function mktLoadUrl() {
  const url = document.getElementById('mkt-url').value.trim();
  if (!url) return;
  await _mktFetch(url, '');
}

async function _mktFetch(url, mktName) {
  const grid = document.getElementById('mkt-grid');
  grid.innerHTML = '<div class="mkt-empty">⏳ 加载中…</div>';
  mktStatus('');
  try {
    const r = await fetch(`/api/marketplace/fetch?url=${encodeURIComponent(url)}`);
    const d = await r.json();
    if (!d.ok) {
      grid.innerHTML = `<div class="mkt-empty" style="color:var(--red)">❌ ${esc(d.error||'加载失败')}</div>`;
      return;
    }
    _mktPlugins = d.plugins || [];
    _mktInstalled = new Set(d.installed || []);
    _mktName = mktName || d.name || '';
    mktStatus(`${_mktPlugins.length} 个插件，已安装 ${_mktInstalled.size} 个`);
    mktRenderGrid(_mktPlugins);
  } catch (e) {
    grid.innerHTML = `<div class="mkt-empty" style="color:var(--red)">❌ ${esc(e.message)}</div>`;
  }
}

function mktFilter() {
  const q = document.getElementById('mkt-search').value.toLowerCase();
  const filtered = q
    ? _mktPlugins.filter(p =>
        (p.name||'').toLowerCase().includes(q) ||
        (p.description||'').toLowerCase().includes(q))
    : _mktPlugins;
  mktRenderGrid(filtered);
}

function mktRenderGrid(plugins) {
  const grid = document.getElementById('mkt-grid');
  if (!plugins.length) {
    grid.innerHTML = '<div class="mkt-empty">暂无结果</div>';
    return;
  }
  grid.innerHTML = '';
  for (const p of plugins) {
    const isInstalled = _mktInstalled.has(p.name);
    const skillCount = (p.skills || []).length;
    const card = document.createElement('div');
    card.className = 'mkt-card' + (isInstalled ? ' installed' : '');
    card.innerHTML = `
      <div class="mkt-card-name">
        ${esc(p.name)}
        ${isInstalled ? '<span class="installed-badge">✓ 已安装</span>' : ''}
      </div>
      <div class="mkt-card-desc">${esc(p.description||'')}</div>
      ${skillCount ? `<div class="mkt-card-skills">📦 ${skillCount} 个 skill</div>` : ''}
      <div class="mkt-card-actions">
        ${isInstalled
          ? `<button class="mkt-btn danger" onclick="mktUninstall('${esc(p.name)}')">卸载</button>`
          : `<button class="mkt-btn primary" onclick="mktInstall('${esc(p.name)}')">安装</button>`
        }
        ${p.homepage ? `<button class="mkt-btn" onclick="window.open('${esc(p.homepage)}','_blank')">详情</button>` : ''}
      </div>`;
    grid.appendChild(card);
  }
}

async function mktInstall(name) {
  if (_mktBusy) return;
  _mktBusy = true;
  _mktStreamAction('/api/marketplace/install', { plugin: name, marketplace: _mktName }, async () => {
    _mktBusy = false;
    // Refresh installed status
    await _mktFetch(document.getElementById('mkt-url').value.trim(), _mktName);
    // Refresh local skills sidebar
    loadSkills();
  });
}

async function mktUninstall(name) {
  if (_mktBusy) return;
  if (!confirm(`确认卸载插件 "${name}"？`)) return;
  _mktBusy = true;
  _mktStreamAction('/api/marketplace/uninstall', { plugin: name }, async () => {
    _mktBusy = false;
    await _mktFetch(document.getElementById('mkt-url').value.trim(), _mktName);
    loadSkills();
  });
}

async function _mktStreamAction(endpoint, body, onDone) {
  const logEl = document.getElementById('mkt-log');
  logEl.innerHTML = '';
  logEl.classList.add('show');

  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data:\s*/, '').trim();
        if (!line) continue;
        try {
          const ev = JSON.parse(line);
          if (ev.done) { if (onDone) onDone(); break; }
          if (ev.msg) {
            const span = document.createElement('span');
            span.className = `ll-${ev.level||'info'}`;
            span.textContent = ev.msg + '\n';
            logEl.appendChild(span);
            logEl.scrollTop = logEl.scrollHeight;
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    const span = document.createElement('span');
    span.className = 'll-error';
    span.textContent = `错误: ${e.message}\n`;
    logEl.appendChild(span);
    if (onDone) onDone();
  }
}

function mktStatus(msg, isErr) {
  const el = document.getElementById('mkt-status');
  if (el) {
    el.textContent = msg;
    el.style.color = isErr ? 'var(--red)' : 'var(--muted)';
  }
}

// ── Install / Setup modal ────────────────────────────────
let _instRunning = false;

async function openInstallModal() {
  document.getElementById('install-overlay').classList.add('show');
  // Load saved model if any
  try {
    const r = await fetch('/api/install/status');
    const d = await r.json();
    _renderInstStatus(d);
    // Fill model from settings if available
  } catch (_) {}
  // Load current config
  try {
    const sf = await fetch('/api/config');
    // We don't expose model via /api/config but load it another way
  } catch (_) {}
}

function closeInstallModal(ev) {
  if (ev && ev.target !== document.getElementById('install-overlay')) return;
  document.getElementById('install-overlay').classList.remove('show');
}

function _renderInstStatus(d) {
  const grid = document.getElementById('inst-status-grid');
  const items = [
    { key:'nvm',    icon:'🔧', name:'nvm',        ver: d.nvm?.path },
    { key:'node',   icon:'🟢', name:'Node.js',    ver: d.node?.version },
    { key:'npm',    icon:'📦', name:'npm',         ver: d.npm?.version },
    { key:'claude', icon:'⚡', name:'Claude Code', ver: d.claude?.version },
    { key:'auth',   icon:'🔑', name:'认证',        ver: d.auth?.info || (d.auth?.ok ? '已配置' : '未配置') },
  ];
  grid.innerHTML = items.map(it => {
    const ok = d[it.key]?.ok;
    return `<div class="inst-cell ${ok?'ok':'err'}">
      <span class="ic-icon">${it.icon}</span>
      <span class="ic-name">${it.name}</span>
      <span class="ic-ver">${esc(it.ver||'未安装')}</span>
    </div>`;
  }).join('');
  // Show claude path
  if (d.claude?.path) {
    document.getElementById('inst-bin').placeholder = d.claude.path;
  }
}

// 开始安装器环境检测
async function instCheck() {
  instLog('检测环境...\n');
  await instRun('check');
}

// 执行安装器命令（流式输出）
async function instRun(action) {
  if (_instRunning) return;
  _instRunning = true;
  ['inst-check-btn','inst-node-btn','inst-claude-btn','inst-update-btn'].forEach(id => {
    const el = document.getElementById(id); if (el) el.disabled = true;
  });
  const logEl = document.getElementById('inst-log');
  logEl.innerHTML = '';

  try {
    const resp = await fetch('/api/install/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });

    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data:\s*/, '').trim();
        if (!line) continue;
        try {
          const ev = JSON.parse(line);
          if (ev.done) {
            instLog('\n' + t('done') + '\n', 'success');
            // Refresh status
            const sr = await fetch('/api/install/status');
            _renderInstStatus(await sr.json());
            break;
          }
          if (ev.msg) instLog(ev.msg + '\n', ev.level || 'info');
        } catch (_) {
          instLog(line + '\n');
        }
      }
    }
  } catch (e) {
    instLog(`错误: ${e.message}\n`, 'error');
  } finally {
    _instRunning = false;
    ['inst-check-btn','inst-node-btn','inst-claude-btn','inst-update-btn'].forEach(id => {
      const el = document.getElementById(id); if (el) el.disabled = false;
    });
  }
}

function instLog(msg, level) {
  const el = document.getElementById('inst-log');
  if (!el) return;
  const div = document.createElement('div');
  div.className = `ll-${level||'info'}`;
  div.textContent = translateInstallLog(msg);
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

// 保存安装器配置
async function instSaveConfig() {
  const apiKey  = document.getElementById('inst-apikey').value.trim();
  const baseUrl = document.getElementById('inst-base-url').value.trim();
  const model   = document.getElementById('inst-model').value.trim();
  const bin     = document.getElementById('inst-bin').value.trim();
  try {
    const r = await fetch('/api/install/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey, base_url: baseUrl, model, claude_bin: bin })
    });
    const d = await r.json();
    if (d.ok) {
      toast(`配置已保存: ${d.changed.join(', ') || '(无变更)'}`);
      document.getElementById('inst-apikey').value = '';
      document.getElementById('inst-base-url').value = '';
      if (apiKey) document.getElementById('inst-apikey').placeholder = '已保存（留空则不修改）';
      if (baseUrl) document.getElementById('inst-base-url').placeholder = '已保存（留空则不修改）';
    }
  } catch (e) { toast('保存失败: ' + e.message, true); }
}

// ── Right sidebar (Skills + Prompts) ─────────────────────
let _skillsSidebarOpen = localStorage.getItem('right-sidebar-open') === 'true';
let _rightTab = 'skills';

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('skills-sidebar').classList.toggle('collapsed', !_skillsSidebarOpen);
});

// 打开右侧面板（skills/prompts/history）
function openRightPanel(tab) {
  const wasOpen = _skillsSidebarOpen;
  const sameTab = _rightTab === tab;
  if (wasOpen && sameTab) {
    // toggle close if already on this tab
    _skillsSidebarOpen = false;
    document.getElementById('skills-sidebar').classList.add('collapsed');
  } else {
    _skillsSidebarOpen = true;
    const sidebar = document.getElementById('skills-sidebar');
    sidebar.classList.remove('collapsed');
    // Restore default width when opening via toolbar button
    sidebar.style.width = '190px';
    switchRightTab(tab);
  }
  localStorage.setItem('right-sidebar-open', _skillsSidebarOpen);
  setTimeout(() => {
    const srv = activeSrv();
    if (srv && srv.activeSession) safeFit(srv, srv.activeSession);
  }, 220);
}

// 切换右侧面板折叠状态
function toggleSkillsSidebar() { openRightPanel('skills'); }

// 切换右侧标签页（skills/prompts/history）
function switchRightTab(tab) {
  _rightTab = tab;
  ['skills', 'prompts', 'history'].forEach(t => {
    document.getElementById('right-pane-' + t).style.display = t === tab ? '' : 'none';
    document.getElementById('sk-tab-' + t).classList.toggle('active', t === tab);
  });
  if (tab === 'skills')  loadSkills();
  if (tab === 'prompts') loadPrompts();
  if (tab === 'history') loadSessionHistory();
}

// 加载会话历史（Claude 会话的提示词记录）
async function loadSessionHistory() {
  const el = document.getElementById('history-list');
  const srv = activeSrv();
  if (!srv || !srv.activeSession) {
    el.innerHTML = '<div class="skills-empty">' + t('history_empty_hint') + '</div>';
    return;
  }
  const name = srv.activeSession;
  el.innerHTML = '<div class="skills-empty">' + t('loading') + '</div>';
  try {
    const r = await fetch(`${srvBase(srv)}/api/sessions/${encodeURIComponent(name)}/history`);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const { prompts } = await r.json();
    if (!prompts || prompts.length === 0) {
      el.innerHTML = '<div class="skills-empty">' + t('history_empty') + '</div>';
      return;
    }
    el.innerHTML = '';
    prompts.forEach((p, i) => {
      const item = document.createElement('div');
      item.className = 'hist-prompt-item';
      const preview = p.text.length > 120 ? p.text.slice(0, 120) + '…' : p.text;
      item.innerHTML = `
        <div class="hist-prompt-meta">#${prompts.length - i} <span>${p.ts || ''}</span></div>
        <div class="hist-prompt-text">${escHtml(preview)}</div>`;
      item.title = p.text;
      item.onclick = () => {
        const term = srv && srv.activeSession ? srv.sessions[srv.activeSession]?.term : null;
        if (term) term.paste(p.text);
      };
      el.appendChild(item);
    });
  } catch (e) {
    console.error('Failed to load session history:', e);
    el.innerHTML = '<div class="skills-empty">' + t('history_empty') + '</div>';
  }
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// 加载技能列表
async function loadSkills() {
  const list = document.getElementById('skills-list');
  if (!list) return;
  try {
    const r = await fetch('/api/skills');
    const d = await r.json();
    const skills = d.skills || [];
    if (!skills.length) {
      list.innerHTML = '<div class="skills-empty">' + t('no_skills') + '</div>';
      return;
    }
    list.innerHTML = '';
    for (const s of skills) {
      const el = document.createElement('div');
      el.className = 'skill-item';
      el.dataset.name = s.name;
      const srcTag = s.source && s.source !== 'local'
        ? `<span style="font-size:9px;color:var(--muted);background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:0 4px;margin-left:3px;flex-shrink:0">${esc(s.source)}</span>`
        : '';
      el.innerHTML =
        `<span class="skill-name" style="display:flex;align-items:center;gap:0">/${esc(s.name)}${srcTag}</span>` +
        (s.description ? `<span class="skill-desc">${esc(s.description)}</span>` : '');
      el.addEventListener('click', () => el.classList.toggle('sk-exp'));
      el.addEventListener('dblclick', e => { e.stopPropagation(); insertSkill(s.name); });
      list.appendChild(el);
    }
  } catch (e) {
    console.error('Failed to load skills:', e);
    list.innerHTML = `<div class="skills-empty">${t('load_failed')}</div>`;
  }
}

// 插入技能到当前 Claude 会话
function insertSkill(name) {
  const srv = activeSrv();
  if (!srv || !srv.activeSession) { toast('请先连接一个 Claude 会话', true); return; }
  const s = srv.sessions[srv.activeSession];
  if (!s || !s.ws || s.ws.readyState !== WebSocket.OPEN) { toast('会话未连接', true); return; }
  const bytes = new TextEncoder().encode(`/${name}\n`);
  s.ws.send(JSON.stringify({ type:'input', data: btoa(String.fromCharCode(...bytes)) }));
  if (s.term) s.term.focus();
  toast(`已发送 /${name}`);
}

// ── Session stats modal ───────────────────────────────────
let _statsSessionName = null;

// 打开会话统计模态框
async function openStatsModal(sessionName) {
  _statsSessionName = sessionName;
  document.getElementById('stats-title').textContent = `📊 ${sessionName}`;
  document.getElementById('stats-content').innerHTML = '<div class="stats-loading">加载中…</div>';
  document.getElementById('stats-overlay').classList.add('show');
  await _loadStats(sessionName);
}

// 关闭统计模态框
function closeStatsModal(ev) {
  if (ev && ev.target !== document.getElementById('stats-overlay')) return;
  document.getElementById('stats-overlay').classList.remove('show');
}

// 刷新统计
async function refreshStats() {
  if (_statsSessionName) await _loadStats(_statsSessionName);
}

// 加载统计
async function _loadStats(name) {
  const content = document.getElementById('stats-content');
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(name)}/stats`);
    const d = await r.json();
    if (d.detail || d.error) { content.innerHTML = `<p style="color:var(--red)">${d.detail||d.error}</p>`; return; }
    content.innerHTML = _renderStats(d);
  } catch (e) {
    content.innerHTML = `<p style="color:var(--red)">加载失败: ${e.message}</p>`;
  }
}

// 渲染统计 HTML
function _renderStats(d) {
  const dur = d.duration_seconds || 0;
  const durStr = dur < 60 ? `${Math.round(dur)}s`
               : dur < 3600 ? `${Math.floor(dur/60)}m${Math.round(dur%60)}s`
               : `${Math.floor(dur/3600)}h${Math.floor((dur%3600)/60)}m`;

  const tk = d.tokens || {};
  const totalIn  = (tk.input||0) + (tk.cache_read||0) + (tk.cache_creation||0);
  const totalOut = tk.output || 0;
  const fmtNum   = n => n >= 1000 ? `${(n/1000).toFixed(1)}k` : String(n);
  const turns    = d.turns || {};
  const cost     = d.cost_usd || 0;

  const cells = [
    { label: t('stats_runtime'), val: durStr, sub: d.alive ? t('stats_running') : t('stats_stopped'), cls: d.alive?'green':'' },
    { label: t('stats_turns'), val: (turns.user||0)+(turns.assistant||0), sub: t('stats_turns_sub', {user: turns.user||0, ai: turns.assistant||0}), cls:'blue' },
    { label: t('stats_input_tokens'), val: fmtNum(totalIn), sub: t('stats_input_sub', {direct: fmtNum(tk.input||0), cache_read: fmtNum(tk.cache_read||0)}), cls:'' },
    { label: t('stats_output_tokens'), val: fmtNum(totalOut), sub: t('stats_output_sub', {cache_write: fmtNum(tk.cache_creation||0)}), cls:'' },
    { label: t('stats_tool_calls'), val: d.tool_uses||0, sub: t('stats_tool_calls_sub'), cls:'' },
    { label: t('stats_cost'), val: cost > 0 ? `$${cost.toFixed(4)}` : '—', sub:'USD', cls: cost>0?'yellow':'' },
    { label: t('stats_pid'), val: d.pid||'—', sub: t('stats_buffer', {kb: ((d.buffer_bytes||0)/1024).toFixed(1)}), cls:'', wide:false },
    { label: t('stats_workdir'), val: '', sub: d.workdir||'—', cls:'', wide:true },
  ];

  return `<div class="stats-grid">${cells.map(c =>
    `<div class="stats-cell ${c.wide?'wide':''} ${c.cls||''}">
      <div class="s-label">${c.label}</div>
      ${c.val!==''?`<div class="s-val">${esc(String(c.val))}</div>`:''}
      <div class="s-sub">${esc(c.sub)}</div>
    </div>`
  ).join('')}</div>`;
}

// ── i18n ─────────────────────────────────────────────────
const _i18n = {
  zh: {
    // Header toolbar
    subtitle:          'Claude Code OS Shell',
    cc_terminal:       'CC 终端',
    status:            '状态',
    server_settings:   '⚙ 服务器设置',
    server_settings_text: '服务器设置',
    im_channel:        'IM频道',
    skills_market:     'Skills市场',
    install_btn:       'ClaudeCode 安装',
    theme_dark:        '🌙',
    theme_light:       '☀',
    logout:            '退出',

    // Sidebar – card list
    cards:             '卡片',
    new_card:          '新建',
    no_cards:          '暂无卡片<br>点击 ＋ 新建',
    session_list:      '会话列表',
    add_server_conn:   '添加服务器连接',
    sidebar_resize:    '',

    // Card states
    running:           '运行中',
    stopped:           '已停止',
    connected:         '已连接',
    disconnected:      '未连接',
    connecting:        '连接中',
    not_started:       '未启动',

    // Card actions
    delete:            '删除',
    start:             '▶ 启动',
    stop:              '■ 停止',
    waiting_events:    '等待事件…',
    not_running:       '（未运行）',
    double_click_rename: '双击重命名',
    rename:            '重命名',
    more:              '更多',
    not_connected:     '未连接',
    connect:           '连接',
    close:             '关闭',
    status_running:    '运行中',
    status_connecting: '连接中',
    status_stopped:    '已退出',
    feishu_connected:  '已连接',
    feishu_connecting: '连接中',
    feishu_disconnected: '未连接',
    clear_log:         '清空日志',
    log_cleared:       '日志已清空',
    stats:             '📊 统计',

    // Server settings
    server_settings_title: '⚙ 服务器设置',
    cfg_tab_basic:     '⚙ 基本设置',
    cfg_tab_files:     '📁 配置文件参考',
    cfg_basic:         '⚙ 基本设置',
    cfg_files:         '📁 配置文件参考',
    label_listen_ip:   '监听 IP',
    label_port:        '端口',
    cfg_hint:          '监听地址和端口由启动参数决定，如需修改请重启服务时指定 --host 和 --port 参数。',
    cfg_close_btn:     '关闭',
    cfg_env_section:   '环境变量',
    cfg_args_section:  '启动参数',
    cfg_files_section: '运行时配置文件',
    cfg_cards_section: 'cards.json — Card 字段说明',
    cfg_paths_section: '其他运行时路径',
    cfg_hint_default:  '（默认',
    cfg_table_var:     '变量',
    cfg_table_default: '默认值',
    cfg_table_desc:    '说明',
    cfg_table_param:   '参数',
    cfg_table_file:    '文件',
    cfg_table_usage:   '用途',
    cfg_table_fields:  '关键字段',
    cfg_table_field:   '字段',
    cfg_table_type:    '适用类型',

    // Toast messages
    toast_saved:       '配置已保存',
    toast_created:     '已创建',
    toast_started:     '已启动',
    toast_stopped:     '已停止',
    toast_deleted:     '已删除',
    toast_renamed:     '已重命名',
    toast_restored:    '已恢复',
    toast_connected:   '已连接',
    toast_save_failed: '保存失败',
    toast_create_failed: '创建失败',
    toast_delete_failed: '删除失败',
    toast_rename_failed: '重命名失败',
    toast_start_failed: '启动失败',
    toast_stop_failed: '停止失败',
    toast_refresh_failed: '刷新失败',
    toast_load_failed: '加载失败',
    toast_select_server: '请先选择服务器',
    toast_fill_ip:     '请填写 IP 地址',
    toast_fill_host_user: '请填写主机和用户名',
    toast_fill_app_id: '请填写 App ID',
    toast_fill_secret: '请填写 App Secret',
    toast_fill_token:  '请填写 Bot Token',
    toast_fill_app_key: '请填写 App Key',
    toast_fill_ws_url: '请填写 WebSocket URL',
    toast_fill_corp_id: '请填写 Corp ID',
    toast_fill_agent_id: '请填写 Agent ID',
    toast_unknown_type: '未知类型',
    toast_auto_created_dir: '已自动创建目录',
    toast_confirm_terminate: '终止会话 "{name}"？',
    toast_confirm_delete_session: '确定删除这个会话吗？',
    toast_confirm_delete_card: '确定删除这个卡片吗？（正在运行的服务也会停止）',

    // Right sidebar
    skills:              'Skills',
    prompts:             'Prompt 模板',
    history_tab:         '提问历史',
    loading:             '加载中…',
    no_skills:           '未找到 skill<br>~/.claude/skills/',
    no_templates:        '暂无模板',
    history_empty_hint:  '选择会话后显示提问记录',
    history_empty:       '暂无历史记录',
    local:               '本地',
    local_server_label:  '🖥 本地',
    load_failed:         '加载失败',
    local_terminal:    '本地终端',
    ssh_terminal:      'SSH 终端',
    no_local_terminal: '暂无本地终端<br>点击 ＋ 新建',
    no_ssh_session:    '暂无 SSH 会话<br>点击 ＋ 新建',
    no_claude_session: '暂无 Claude 会话<br>点击 ＋ 新建',
    session_exit_close: '会话已退出，2 秒后关闭卡片',
    add_connection:    '添加连接',
    new_ssh_terminal:  '新建 SSH 终端',
    connect_btn:       '连接',
    has_secret:        '✓Secret',
    no_secret:         '⚠无 Secret',
    token_configured:  '✓已配置',
    token_saved:       '✓已保存',
    token_not_configured: '⚠未配置',
    delay_label:       '延迟',
    status_label:      '状态',
    args_label:        '参数',
    workdir_label:     '工作目录',
    reply_delay_label: '回复延迟',
    click_to_switch_terminal: '点击切换终端',
    click_to_expand:   '点击展开配置',
    rename_card:       '重命名',
    expand_collapse:   '展开/折叠',
    running_time:      '运行时长',
    conversation_turns: '对话轮数',
    input_tokens:      '输入 Token',
    output_tokens:     '输出 Token',
    tool_calls:        '工具调用',
    cost_estimate:     '费用估算',
    pid_label:         'PID',
    buffer_label:      '缓冲区',
    alive_running:     '●运行中',
    stopped_label:     '■已停止',
    user_turns:        '用户',
    ai_turns:          'AI',
    direct_read:       '直接',
    cache_read:        '缓存读',
    cache_write:       '缓存写',
    usd:               'USD',

    // New card modal
    create_card:       '新建卡片',
    create:            '创建',
    cancel:            '取消',
    claude_session:    'Claude 会话',
    session_name:      '会话名称',
    workdir:           '工作目录',
    args:              'Claude 参数（可选）',
    auto_start_label:  '创建后立即启动',

    // New IM modal
    new_im_config:     '新建IM配置',
    no_im_bots:        '暂无 IM 机器人<br>点击 ＋ 新建',
    im_feishu:         '飞书',
    im_dingtalk:       '钉钉',
    im_wework:         '企业微信',

    // Feishu legacy
    feishu:            '飞书',
    feishu_bot:        '飞书 Bot',
    app_id:            'App ID',
    app_secret:        'App Secret',
    reply_delay:       '回复延迟(秒)',

    // Terminal welcome
    select_or_create:  '选择或新建会话',
    select_hint:       '从左侧栏创建新会话，或点击已有会话名称连接',
    clear_screen:      '清屏',
    kill:              '终止',
    scheduled_tasks:   '定时任务',

    // Stats modal
    stats_runtime:     '运行时长',
    stats_running:     '●运行中',
    stats_stopped:     '■已停止',
    stats_turns:       '对话轮数',
    stats_turns_sub:   '用户 {user} / AI {ai}',
    stats_input_tokens:'输入 Token',
    stats_input_sub:   '直接 {direct}  缓存读 {cache_read}',
    stats_output_tokens:'输出 Token',
    stats_output_sub:  '缓存写 {cache_write}',
    stats_tool_calls:  '工具调用',
    stats_tool_calls_sub:'Tool use 次数',
    stats_cost:        '费用估算',
    stats_pid:         'PID',
    stats_buffer:      '缓冲区 {kb}KB',
    stats_workdir:     '工作目录',

    skills_panel:      'Skills 面板',
    prompt_templates_panel: 'Prompt 模板',
    feishu_msg_hint:   '飞书消息将在此显示',
    refresh_btn:       '刷新',
    hist_summary:      '📋 会话历史总结',
    hist_select_hint:  '选择左侧日志文件查看或生成总结',
    user_history:      '用户提问历史',
    prompt_search:     '搜索…',
    no_templates_msg:  '暂无模板',

    // Skills marketplace
    skills_market_title: '🏪 Skills 市场',
    mkt_load:          '加载',
    mkt_search:        '搜索...',
    mkt_empty:         '选择上方市场或输入 URL 加载插件列表',
    mkt_close:         '关闭',

    // MCP Market
    mcp_market_title:  '🔌 MCP 市场',
    mcp_installed:     '已安装',
    mcp_none_installed: '暂无',
    mcp_custom_add:    '自定义添加',
    mcp_name_ph:       '名称',
    mcp_cmd_ph:        '命令 (如 npx)',
    mcp_args_ph:       '参数 (空格分隔)',
    mcp_env_ph:        '环境变量 JSON {"K":"V"}',
    mcp_add_btn:       '添加',
    mcp_common:        '常用 MCP 服务',
    mcp_close_btn:     '关闭',

    // Prompt management
    prompt_mgmt_title: '📝 Prompt 模板管理',
    pm_search:         '搜索…',
    pm_new_template:   '新建模板',
    pm_name_ph:        '名称',
    pm_prompt_ph:      'Prompt 内容…',
    pm_reset:          '清空',
    pm_save:           '保存',
    pm_close:          '关闭',

    // Install modal
    install_title:     '⬇ ClaudeCode 安装 / 配置',
    inst_checking:     '检查中…',
    inst_check_env:    '↻ 检测环境',
    inst_install_node: '安装 Node.js',
    inst_install_claude: '安装 Claude Code',
    inst_update_claude: '更新 Claude Code',
    inst_log_hint:     '点击「检测环境」查看当前状态',
    inst_config_section: '配置',
    inst_apikey_lbl:   'Anthropic API Key（留空则不修改）',
    inst_base_url_lbl: 'API Base URL（留空则不修改）',
    inst_model_lbl:    '模型（如 claude-sonnet-4-5，留空则不修改）',
    inst_bin_lbl:      'Claude 可执行路径（留空则自动检测）',
    inst_close:        '关闭',
    inst_save_config:  '保存配置',
    done:              '✅ 完成',

    // Stats panel
    logs_tab:          '📋 日志',
    stats_tab:         '📊 Token 统计',
    trend_tab:         '📈 趋势图',
    sp_log_clear:      '清空',
    sp_auto_scroll:    '自动滚动',
    sp_no_logs:        '暂无日志',
    sp_loading:        '加载中…',
    sp_days_lbl:       '天数:',
    days_7:            '7 天',
    days_14:           '14 天',
    days_30:           '30 天',
    session_stats_title: '📊 会话统计',
    stats_loading:     '加载中…',
    stats_refresh:     '↻ 刷新',
    stats_close:       '关闭',

    // New card modal
    nc_type_claude:    '🐻 Claude 会话',
    nc_name_ph:        'auto',
    nc_workdir_lbl:    '工作目录',
    nc_args_ph:        '--no-update ...',
    nc_fname_ph:       '飞书 Bot',
    nc_delay_lbl:      '回复延迟 (秒)',

    // Tasks modal
    tasks_modal_title: '⏰ 定时任务',
    task_new_btn:      '＋ 新建任务',
    task_no_tasks:     '暂无定时任务',
    task_form_title:   '新建任务',
    task_name_lbl:     '任务名称',
    task_name_ph:      '每日提醒',
    task_session_lbl:  '目标 Session',
    task_session_ph:   'session1',
    task_prompt_lbl:   '提词内容',
    task_prompt_ph:    '请输入要发送给 Claude 的内容…',
    task_interval_radio: '间隔触发',
    task_cron_radio:   'Cron 表达式',
    task_interval_every: '每',
    task_interval_mins: '分钟触发一次',
    task_cron_lbl:     'Cron 表达式',
    task_cron_hint:    '(分 时 日 月 周，如',
    task_cron_example: ' = 工作日 9 点)',
    task_cancel:       '取消',
    task_save_btn:     '保存',
    task_close_btn:    '关闭',

    // New IM modal
    im_type_feishu:    '🔔 飞书',
    im_type_telegram:  '✈️ Telegram',
    im_type_dingtalk:  '📎 钉钉',
    im_type_qq:        '🐧 QQ',
    im_type_wework:    '💼 企业微信',
    im_fname_ph:       '飞书 Bot',
    im_appid_ph:       'cli_xxxxxxxxxx',
    im_secret_ph:      '••••••••••',
    im_delay_lbl:      '回复延迟 (秒)',
    im_tg_name_ph:     'TelegramBot',
    im_tg_token_ph:    '123456789:AABBcc...',
    im_tg_delay_lbl:   '回复延迟 (秒)',
    im_tg_hint:        '从 @BotFather 获取 Bot Token。无需公网 IP，使用长轮询接收消息。',
    im_dt_name_ph:     '钉钉 Bot',
    im_dt_key_ph:      'dingXXXXXXXXX',
    im_dt_secret_ph:   '••••••••••',
    im_dt_delay_lbl:   '回复延迟 (秒)',
    im_dt_hint:        '需安装 <code>pip install dingtalk-stream</code>。使用钉钉开放平台企业内部机器人凭证。',
    im_qq_name_ph:     'QQ Bot',
    im_qq_ws_ph:       'ws://127.0.0.1:3001',
    im_qq_token_ph:    '留空则不验证',
    im_qq_delay_lbl:   '回复延迟 (秒)',
    im_qq_hint:        '兼容 NapCatQQ / LLOneBot / go-cqhttp 等 OneBot v11 实现。',
    im_ww_name_ph:     '企微 Bot',
    im_ww_corpid_ph:   'ww00000000000000',
    im_ww_agentid_ph:  '1000001',
    im_ww_secret_ph:   '••••••••••',
    im_ww_token_ph:    '随机字符串',
    im_ww_aeskey_ph:   '43 位随机字符串',
    im_ww_corpid_lbl:  'Corp ID（企业 ID）',
    im_ww_agentid_lbl: 'Agent ID（应用 ID）',
    im_ww_token_lbl:   'Token（消息校验 Token）',
    im_ww_aeskey_lbl:  'EncodingAESKey（43 位）',
    im_ww_delay_lbl:   '回复延迟 (秒)',
    im_ww_hint:        'Webhook 回调地址将在创建后显示。需在企业微信管理后台 → 应用 → 接收消息 中填写该地址。',
    im_create_auto:    '创建后立即启动',
    im_cancel:         '取消',
    im_create_btn:     '创建',

    // Server/connection modal
    srv_modal_title:   '添加连接',
    srv_ct_http:       '🌐 Claude Code',
    srv_ct_local:      '🖥 本地终端',
    srv_ct_ssh:        '🔒 SSH 终端',
    srv_local_shell_lbl: 'Shell（可选，默认 $SHELL）',
    srv_local_hint:    '直接在本机打开一个终端会话，无需 SSH。',
    srv_display_name:  '显示名称（可选）',
    srv_my_server:     '我的服务器',
    srv_ip_lbl:        'IP 地址',
    srv_port_lbl:      '端口',
    srv_hint:          '填写远程 Claude Code 服务器的地址和端口。',
    srv_hist_lbl:      '历史连接',
    srv_new_div:       '新建',
    srv_ssh_label_ph:  '生产服务器',
    srv_ssh_host_lbl:  '主机 / IP',
    srv_ssh_port_lbl:  '端口',
    srv_ssh_user_lbl:  '用户名',
    srv_ssh_pass_lbl:  '密码（可选）',
    srv_ssh_pass_ph:   '留空则用密钥',
    srv_ssh_save_pass: '保存密码',
    srv_ssh_key_lbl:   '私钥路径（可选）',
    srv_cancel:        '取消',
    srv_connect_btn:   '连接',

    // Server settings modal
    cfg_title:         '⚙ 服务器设置',
    cfg_basic_tab:     '⚙ 基本设置',
    cfg_files_tab:     '📁 配置文件参考',
    cfg_listen_ip:     '监听 IP',
    cfg_port:          '端口',
    cfg_restart_hint:  '⚠ 修改并重启后浏览器将自动跳转到新地址。',
    cfg_cancel:        '取消',
    cfg_save_only:     '仅保存',
    cfg_save_restart:  '保存并重启',

    // Config reference
    cfg_env_vars:      '环境变量',
    cfg_col_var:       '变量',
    cfg_col_default:   '默认值',
    cfg_col_desc:      '说明',
    cfg_druidclaw_token: 'Web 访问密码（<code>--passwd</code> 可覆盖）',
    cfg_druidclaw_run_dir: '运行时数据目录（所有 JSON 配置文件所在位置）',
    cfg_druidclaw_web_host: '绑定地址（启动时写入，优先于 config.json）',
    cfg_druidclaw_web_port: '监听端口（启动时写入，优先于 config.json）',
    cfg_read_config:   '读 config.json',
    cfg_read_env:      '读 DRUIDCLAW_TOKEN',
    cfg_startup_args:  '启动参数',
    cfg_col_param:     '参数',
    cfg_host_desc:     '绑定地址，覆盖已保存配置',
    cfg_port_desc:     '监听端口，覆盖已保存配置',
    cfg_passwd_desc:   '访问密码，覆盖 DRUIDCLAW_TOKEN 环境变量',
    cfg_workdir_desc:  '新建会话的默认工作目录',
    cfg_reload_desc:   '代码变更时自动重载（开发用）',
    cfg_runtime_config: '运行时配置文件',
    cfg_col_file:      '文件',
    cfg_col_purpose:   '用途',
    cfg_col_fields:    '关键字段',
    cfg_config_json:   'Web 服务器绑定地址/端口',
    cfg_cards_json:    '所有 Card 配置，重启后自动恢复',
    cfg_cards_fields:  '见下方 Card 字段说明',
    cfg_feishu_json:   '飞书遗留全局凭证（兼容旧版）',
    cfg_bridge_json:   'IM Bridge 通用配置',
    cfg_tasks_json:    '定时任务列表',
    cfg_ssh_hist_json: 'SSH 连接历史（不含密码）',
    cfg_card_fields:   'cards.json — Card 字段说明',
    cfg_col_field:     '字段',
    cfg_col_app_type:  '适用类型',
    cfg_all_types:     '全部',
    cfg_im_types:      'IM 类',
    cfg_field_id:      '自动生成的 8 位 hex ID',
    cfg_field_type:    '<code>claude</code> / <code>feishu</code> / <code>telegram</code> / <code>dingtalk</code> / <code>qq</code> / <code>wework</code>',
    cfg_field_name:    '显示名称',
    cfg_field_workdir: '工作目录（默认 <code>.</code>）',
    cfg_field_auto_start: '启动时自动运行（默认 <code>true</code>）',
    cfg_field_auto_approve: '自动通过权限提示，跳过确认（默认 <code>false</code>）',
    cfg_field_reply_delay: '回复延迟秒数，范围 0.5–60（默认 <code>2.0</code>）',
    cfg_field_args:    '附加 Claude 启动参数数组',
    cfg_field_app_cred: '飞书 App ID + Secret；钉钉 App Key + Secret',
    cfg_field_tg_token: 'Telegram Bot Token',
    cfg_field_qq_ws:   'OneBot v11 WebSocket 地址及可选鉴权 Token',
    cfg_field_ww_cred: '企业微信企业 ID、应用 ID、应用 Secret',
    cfg_field_ww_token: '消息校验 Token 及 43 位 AES Key',
    cfg_other_paths:   '其他运行时路径',
    cfg_col_path:      '路径',
    cfg_path_logs:     'PTY 会话日志（<code>.log</code> 文本 / <code>.raw</code> 二进制录像）',
    cfg_path_socket:   'Unix socket（daemon 模式 IPC）',
    cfg_path_pid:      'daemon 进程 PID 文件',
    cfg_path_skills:   'Skills 侧边栏数据来源',
    cfg_path_ssh_log:  'SSH 会话临时日志',
    cfg_close_btn:     '关闭',

    // Feishu modal
    feishu_modal_title: '🔔 飞书机器人配置',
    f_section_cred:    '应用凭证',
    f_section_status:  '连接状态',
    f_status_disconnected: '未连接',
    f_disconnect_btn:  '断开',
    f_connect_btn:     '保存并连接',
    f_section_bridge:  '消息桥接设置',
    f_delay_lbl:       '回复延迟 (s)',
    f_bridge_hint:     '连接时自动创建 Claude 会话，断开时自动关闭',
    f_section_events:  '最近事件',
    f_no_events:       '暂无事件',
    f_events_update:   '事件将持续更新',
    f_close:           '关闭',

    // Restart overlay
    restart_msg:       '服务器重启中...',
    spin_wait:         '请稍候',

    // Login page
    login_title:       '🐻 DruidClaw',
    login_prompt:      '请输入访问令牌',
    login_token_ph:    '访问令牌',
    login_btn:         '登录',

    // Status panel
    logs:              '日志',
    server_logs:       '服务器日志',
    token_stats:       'Token 统计',
    trend:             '趋势图',
    clear:             '清空',
    auto_scroll:       '自动滚动',
    no_logs:           '暂无日志',
    loading:           '加载中…',
    days:              '天数',
    total_input:       '总输入 Token',
    total_output:      '总输出 Token',
    total_cost:        '总费用',
    total_turns:       '总对话轮次',
    sys_badge:         '系统',
    user_badge:        '用户',
    claude_badge:      'Claude',
    error_badge:       '错误',

    // Server/connection modal
    local_term:        '本地终端',
    ssh_term:          'SSH 终端',
    local_shell_label: 'Shell（可选，默认 $SHELL）',
    local_hint:        '直接在本机打开一个终端会话，无需 SSH。',

    // Skills sidebar
    skills_title:      'Skills',
    prompts:           'Prompt 模板',
    prompt_templates:  'Prompt 模板',
    history:           '历史',
    history_tab:       '提问历史',
    mcp_market:        'MCP 市场',
    mcp_market_btn:    'MCP 市场',
    prompt_btn:        'Prompt 模板',
    prompt_mgmt:       '模板管理',
    toggle_sidebar:    '折叠侧栏',
  },
  en: {
    // Header toolbar
    subtitle:          'Claude Code OS Shell',
    cc_terminal:       'Claude Code Terminal',
    status:            'Status',
    server_settings:   '⚙ Settings',
    cfg_basic:         '⚙ Basic',
    cfg_files:         '📁 Config Files',
    cfg_tab_basic:     '⚙ Basic',
    cfg_tab_files:     '📁 Config Files',
    im_channel:        'IM Bots',
    skills_market:     'Skills Market',
    install_btn:       'Install',
    theme_dark:        '🌙',
    theme_light:       '☀',
    logout:            'Logout',

    // Sidebar – card list
    cards:             'Cards',
    new_card:          'New',
    no_cards:          'No cards<br>Click ＋ to create',
    session_list:      'Sessions',
    add_server_conn:   'Add Server Connection',
    sidebar_resize:    '',

    // Card states
    running:           'Running',
    stopped:           'Stopped',
    connected:         'Connected',
    disconnected:      'Disconnected',
    connecting:        'Connecting…',
    not_started:       'Not Started',

    // Card actions
    delete:            'Delete',
    start:             '▶ Start',
    stop:              '■ Stop',
    waiting_events:    'Waiting for events…',
    not_running:       '(Not running)',
    double_click_rename: 'Double-click to rename',
    rename:            'Rename',
    more:              'More',
    not_connected:     'Not connected',
    connect:           'Connect',
    close:             'Close',
    status_running:    'Running',
    status_connecting: 'Connecting',
    status_stopped:    'Stopped',
    feishu_connected:  'Connected',
    feishu_connecting: 'Connecting',
    feishu_disconnected: 'Disconnected',
    clear_log:         'Clear Log',
    log_cleared:       'Log cleared',
    stats:             '📊 Stats',

    // Toast messages
    toast_saved:       'Saved',
    toast_created:     'Created',
    toast_started:     'Started',
    toast_stopped:     'Stopped',
    toast_deleted:     'Deleted',
    toast_renamed:     'Renamed',
    toast_restored:    'Restored',
    toast_connected:   'Connected',
    toast_save_failed: 'Save failed',
    toast_create_failed: 'Create failed',
    toast_delete_failed: 'Delete failed',
    toast_rename_failed: 'Rename failed',
    toast_start_failed: 'Start failed',
    toast_stop_failed: 'Stop failed',
    toast_refresh_failed: 'Refresh failed',
    toast_load_failed: 'Load failed',
    toast_select_server: 'Please select a server first',
    toast_fill_ip:     'Please enter IP address',
    toast_fill_host_user: 'Please enter host and username',
    toast_fill_app_id: 'Please enter App ID',
    toast_fill_secret: 'Please enter App Secret',
    toast_fill_token:  'Please enter Bot Token',
    toast_fill_app_key: 'Please enter App Key',
    toast_fill_ws_url: 'Please enter WebSocket URL',
    toast_fill_corp_id: 'Please enter Corp ID',
    toast_fill_agent_id: 'Please enter Agent ID',
    toast_unknown_type: 'Unknown type',
    toast_auto_created_dir: 'Directory created',
    toast_confirm_terminate: 'Terminate session "{name}"?',
    toast_confirm_delete_session: 'Are you sure you want to delete this session?',
    toast_confirm_delete_card: 'Are you sure you want to delete this card? (Running services will also stop)',

    // Right sidebar
    skills:              'Skills',
    prompts:             'Prompts',
    history_tab:         'History',
    loading:             'Loading…',
    no_skills:           'No skills found<br>~/.claude/skills/',
    no_templates:        'No templates',
    history_empty_hint:  'Select a session to view history',
    history_empty:       'No history',
    local:               'Local',
    local_server_label:  '🖥 Local',
    load_failed:         'Load failed',
    local_terminal:    'Local Terminal',
    ssh_terminal:      'SSH Terminal',
    no_local_terminal: 'No local terminals<br>Click ＋ to create',
    no_ssh_session:    'No SSH sessions<br>Click ＋ to create',
    no_claude_session: 'No Claude sessions<br>Click ＋ to create',
    session_exit_close: 'Session exited, closing card in 2s',
    add_connection:    'Add Connection',
    new_ssh_terminal:  'New SSH Terminal',
    connect_btn:       'Connect',
    has_secret:        '✓Secret',
    no_secret:         '⚠No Secret',
    token_configured:  '✓Configured',
    token_saved:       '✓Saved',
    token_not_configured: '⚠Not configured',
    delay_label:       'Delay',
    status_label:      'Status',
    args_label:        'Args',
    workdir_label:     'Working Dir',
    reply_delay_label: 'Reply Delay',
    click_to_switch_terminal: 'Click to switch terminal',
    click_to_expand:   'Click to expand config',
    rename_card:       'Rename',
    expand_collapse:   'Expand/Collapse',
    running_time:      'Running time',
    conversation_turns: 'Conversation turns',
    input_tokens:      'Input Tokens',
    output_tokens:     'Output Tokens',
    tool_calls:        'Tool calls',
    cost_estimate:     'Cost estimate',
    pid_label:         'PID',
    buffer_label:      'Buffer',
    alive_running:     '●Running',
    stopped_label:     '■Stopped',
    user_turns:        'User',
    ai_turns:          'AI',
    direct_read:       'Direct',
    cache_read:        'Cache read',
    cache_write:       'Cache write',
    usd:               'USD',

    // New card modal
    create_card:       'New Card',
    create:            'Create',
    cancel:            'Cancel',
    claude_session:    'Claude Session',
    session_name:      'Session Name',
    workdir:           'Working Dir',
    args:              'Claude Args (optional)',
    auto_start_label:  'Auto-start after creation',

    // New IM modal
    new_im_config:     'New IM Config',
    no_im_bots:        'No IM bots<br>Click ＋ to create',
    im_feishu:         'Feishu',
    im_dingtalk:       'DingTalk',
    im_wework:         'WeCom',

    // Feishu legacy
    feishu:            'Feishu',
    feishu_bot:        'Feishu Bot',
    app_id:            'App ID',
    app_secret:        'App Secret',
    reply_delay:       'Reply Delay (s)',

    // Terminal welcome
    select_or_create:  'Select or Create Session',
    select_hint:       'Create a new session from the sidebar, or click an existing one',
    clear_screen:      'Clear',
    kill:              'Kill',
    scheduled_tasks:   'Scheduled Tasks',

    // Stats modal
    stats_runtime:     'Runtime',
    stats_running:     '●Running',
    stats_stopped:     '■Stopped',
    stats_turns:       'Turns',
    stats_turns_sub:   'User {user} / AI {ai}',
    stats_input_tokens:'Input Tokens',
    stats_input_sub:   'Direct {direct}  Cache read {cache_read}',
    stats_output_tokens:'Output Tokens',
    stats_output_sub:  'Cache write {cache_write}',
    stats_tool_calls:  'Tool Calls',
    stats_tool_calls_sub:'Tool use count',
    stats_cost:        'Cost',
    stats_pid:         'PID',
    stats_buffer:      'Buffer {kb}KB',
    stats_workdir:     'Working Dir',

    skills_panel:      'Skills Panel',
    prompt_templates_panel: 'Prompt Templates',
    feishu_msg_hint:   'Feishu messages will appear here',
    refresh_btn:       'Refresh',
    hist_summary:      '📋 Session History Summary',
    hist_select_hint:  'Select a log file from the left to view or generate summary',
    user_history:      'User Prompt History',
    prompt_search:     'Search…',
    no_templates_msg:  'No templates',
    history_empty_hint: 'Select a session to view prompt history',
    loading:           'Loading…',
    prompts:           'Prompts',

    // Skills marketplace
    skills_market_title: '🏪 Skills Market',
    mkt_load:          'Load',
    mkt_search:        'Search...',
    mkt_empty:         'Select a marketplace above or enter URL to load plugins',
    mkt_close:         'Close',

    // MCP Market
    mcp_market_title:  '🔌 MCP Market',
    mcp_installed:     'Installed',
    mcp_none_installed: 'None',
    mcp_custom_add:    'Custom Add',
    mcp_name_ph:       'Name',
    mcp_cmd_ph:        'Command (e.g., npx)',
    mcp_args_ph:       'Args (space separated)',
    mcp_env_ph:        'Env Vars JSON {"K":"V"}',
    mcp_add_btn:       'Add',
    mcp_common:        'Common MCP Services',
    mcp_close_btn:     'Close',

    // Prompt management
    prompt_mgmt_title: '📝 Prompt Templates Management',
    pm_search:         'Search…',
    pm_new_template:   'New Template',
    pm_name_ph:        'Name',
    pm_prompt_ph:      'Prompt Content…',
    pm_reset:          'Reset',
    pm_save:           'Save',
    pm_close:          'Close',

    // Install modal
    install_title:     '⬇ ClaudeCode Install / Configure',
    inst_checking:     'Checking…',
    inst_check_env:    '↻ Check Environment',
    inst_install_node: 'Install Node.js',
    inst_install_claude: 'Install Claude Code',
    inst_update_claude: 'Update Claude Code',
    inst_log_hint:     'Click "Check Environment" to see current status',
    inst_config_section: 'Configuration',
    inst_apikey_lbl:   'Anthropic API Key (leave empty to keep current)',
    inst_base_url_lbl: 'API Base URL (leave empty to keep current)',
    inst_model_lbl:    'Model (e.g., claude-sonnet-4-5, leave empty to keep current)',
    inst_bin_lbl:      'Claude Binary Path (leave empty for auto-detect)',
    inst_close:        'Close',
    inst_save_config:  'Save Config',
    done:              '✅ Done',

    // Stats panel
    logs_tab:          '📋 Logs',
    stats_tab:         '📊 Token Stats',
    trend_tab:         '📈 Trend',
    sp_log_clear:      'Clear',
    sp_auto_scroll:    'Auto scroll',
    sp_no_logs:        'No logs',
    sp_loading:        'Loading…',
    sp_days_lbl:       'Days:',
    days_7:            '7 days',
    days_14:           '14 days',
    days_30:           '30 days',
    session_stats_title: '📊 Session Stats',
    stats_loading:     'Loading…',
    stats_refresh:     '↻ Refresh',
    stats_close:       'Close',

    // New card modal
    nc_type_claude:    '🐻 Claude Session',
    nc_name_ph:        'auto',
    nc_workdir_lbl:    'Working Dir',
    nc_args_ph:        '--no-update ...',
    nc_fname_ph:       'Feishu Bot',
    nc_delay_lbl:      'Reply Delay (s)',

    // Tasks modal
    tasks_modal_title: '⏰ Scheduled Tasks',
    task_new_btn:      '＋ New Task',
    task_no_tasks:     'No scheduled tasks',
    task_form_title:   'New Task',
    task_name_lbl:     'Task Name',
    task_name_ph:      'Daily Reminder',
    task_session_lbl:  'Target Session',
    task_session_ph:   'session1',
    task_prompt_lbl:   'Prompt Content',
    task_prompt_ph:    'Enter the content to send to Claude…',
    task_interval_radio: 'Interval',
    task_cron_radio:   'Cron Expression',
    task_interval_every: 'Every',
    task_interval_mins: 'minutes',
    task_cron_lbl:     'Cron Expression',
    task_cron_hint:    '(min hour day month weekday, e.g.',
    task_cron_example: ' = Mon-Fri 9am)',
    task_cancel:       'Cancel',
    task_save_btn:     'Save',
    task_close_btn:    'Close',

    // New IM modal
    im_type_feishu:    '🔔 Feishu',
    im_type_telegram:  '✈️ Telegram',
    im_type_dingtalk:  '📎 DingTalk',
    im_type_qq:        '🐧 QQ',
    im_type_wework:    '💼 WeCom',
    im_fname_ph:       'Feishu Bot',
    im_appid_ph:       'cli_xxxxxxxxxx',
    im_secret_ph:      '••••••••••',
    im_delay_lbl:      'Reply Delay (s)',
    im_tg_name_ph:     'TelegramBot',
    im_tg_token_ph:    '123456789:AABBcc...',
    im_tg_delay_lbl:   'Reply Delay (s)',
    im_tg_hint:        'Get Bot Token from @BotFather. No public IP needed, uses long polling.',
    im_dt_name_ph:     'DingTalk Bot',
    im_dt_key_ph:      'dingXXXXXXXXX',
    im_dt_secret_ph:   '••••••••••',
    im_dt_delay_lbl:   'Reply Delay (s)',
    im_dt_hint:        'Requires <code>pip install dingtalk-stream</code>. Use DingTalk open platform enterprise robot credentials.',
    im_qq_name_ph:     'QQ Bot',
    im_qq_ws_ph:       'ws://127.0.0.1:3001',
    im_qq_token_ph:    'Leave empty for no auth',
    im_qq_delay_lbl:   'Reply Delay (s)',
    im_qq_hint:        'Compatible with NapCatQQ / LLOneBot / go-cqhttp and other OneBot v11 implementations.',
    im_ww_name_ph:     'WeCom Bot',
    im_ww_corpid_ph:   'ww00000000000000',
    im_ww_agentid_ph:  '1000001',
    im_ww_secret_ph:   '••••••••••',
    im_ww_token_ph:    'Random string',
    im_ww_aeskey_ph:   '43-character random string',
    im_ww_corpid_lbl:  'Corp ID',
    im_ww_agentid_lbl: 'Agent ID',
    im_ww_token_lbl:   'Token',
    im_ww_aeskey_lbl:  'Encoding AES Key',
    im_ww_delay_lbl:   'Reply Delay (s)',
    im_ww_hint:        'Webhook callback URL will be shown after creation. Need to configure it in WeCom Admin Panel → App → Receive Messages.',
    im_create_auto:    'Auto-start after creation',
    im_cancel:         'Cancel',
    im_create_btn:     'Create',

    // Server/connection modal
    srv_modal_title:   'Add Connection',
    srv_ct_http:       '🤖 Claude Code',
    srv_ct_local:      '🖥 Local Shell',
    srv_ct_ssh:        '🔒 SSH Terminal',
    srv_local_shell_lbl: 'Shell (optional, default $SHELL)',
    srv_local_hint:    'Open a local terminal session directly, no SSH needed.',
    srv_display_name:  'Display Name (optional)',
    srv_my_server:     'My Server',
    srv_ip_lbl:        'IP Address',
    srv_port_lbl:      'Port',
    srv_hint:          'Enter remote DruidClaw server address and port.',
    srv_hist_lbl:      'History Connections',
    srv_new_div:       'New',
    srv_ssh_label_ph:  'Production Server',
    srv_ssh_host_lbl:  'Host / IP',
    srv_ssh_port_lbl:  'Port',
    srv_ssh_user_lbl:  'Username',
    srv_ssh_pass_lbl:  'Password (optional)',
    srv_ssh_pass_ph:   'Leave empty for key auth',
    srv_ssh_save_pass: 'Save Password',
    srv_ssh_key_lbl:   'Private Key Path (optional)',
    srv_cancel:        'Cancel',
    srv_connect_btn:   'Connect',

    // Server settings modal
    cfg_title:         '⚙ Server Settings',
    cfg_basic_tab:     '⚙ Basic Settings',
    cfg_files_tab:     '📁 Config Files Reference',
    cfg_listen_ip:     'Listen IP',
    cfg_port:          'Port',
    cfg_restart_hint:  '⚠ Browser will redirect to new address after restart.',
    cfg_cancel:        'Cancel',
    cfg_save_only:     'Save Only',
    cfg_save_restart:  'Save & Restart',

    // Config reference
    cfg_env_vars:      'Environment Variables',
    cfg_col_var:       'Variable',
    cfg_col_default:   'Default',
    cfg_col_desc:      'Description',
    cfg_druidclaw_token: 'Web password (<code>--passwd</code> overrides)',
    cfg_druidclaw_run_dir: 'Runtime data directory (where JSON config files are stored)',
    cfg_druidclaw_web_host: 'Bind address (written at startup, takes precedence over config.json)',
    cfg_druidclaw_web_port: 'Listen port (written at startup, takes precedence over config.json)',
    cfg_read_config:   'Read config.json',
    cfg_read_env:      'Read DRUIDCLAW_TOKEN',
    cfg_startup_args:  'Startup Arguments',
    cfg_col_param:     'Parameter',
    cfg_host_desc:     'Bind address, overrides saved config',
    cfg_port_desc:     'Listen port, overrides saved config',
    cfg_passwd_desc:   'Access password, overrides DRUIDCLAW_TOKEN env var',
    cfg_workdir_desc:  'Default working directory for new sessions',
    cfg_reload_desc:   'Auto-reload on code changes (for development)',
    cfg_runtime_config: 'Runtime Config Files',
    cfg_col_file:      'File',
    cfg_col_purpose:   'Purpose',
    cfg_col_fields:    'Key Fields',
    cfg_config_json:   'Web server bind address/port',
    cfg_cards_json:    'All Card configs, auto-restore after restart',
    cfg_cards_fields:  'See Card Fields section below',
    cfg_feishu_json:   'Feishu legacy global credentials (backward compat)',
    cfg_bridge_json:   'IM Bridge common config',
    cfg_tasks_json:    'Scheduled tasks list',
    cfg_ssh_hist_json: 'SSH connection history (without passwords)',
    cfg_card_fields:   'cards.json — Card Fields',
    cfg_col_field:     'Field',
    cfg_col_app_type:  'App Type',
    cfg_all_types:     'All',
    cfg_im_types:      'IM Bots',
    cfg_field_id:      'Auto-generated 8-char hex ID',
    cfg_field_type:    '<code>claude</code> / <code>feishu</code> / <code>telegram</code> / <code>dingtalk</code> / <code>qq</code> / <code>wework</code>',
    cfg_field_name:    'Display name',
    cfg_field_workdir: 'Working directory (default <code>.</code>)',
    cfg_field_auto_start: 'Auto-start on daemon launch (default <code>true</code>)',
    cfg_field_auto_approve: 'Auto-approve permission prompts (default <code>false</code>)',
    cfg_field_reply_delay: 'Reply delay in seconds, range 0.5–60 (default <code>2.0</code>)',
    cfg_field_args:    'Additional Claude launch args array',
    cfg_field_app_cred: 'Feishu App ID + Secret; DingTalk App Key + Secret',
    cfg_field_tg_token: 'Telegram Bot Token',
    cfg_field_qq_ws:   'OneBot v11 WebSocket URL and optional access token',
    cfg_field_ww_cred: 'WeCom Corp ID, Agent ID, Corp Secret',
    cfg_field_ww_token: 'Message verification Token and 43-char AES Key',
    cfg_other_paths:   'Other Runtime Paths',
    cfg_col_path:      'Path',
    cfg_path_logs:     'PTY session logs (<code>.log</code> text / <code>.raw</code> binary recording)',
    cfg_path_socket:   'Unix socket (daemon mode IPC)',
    cfg_path_pid:      'Daemon process PID file',
    cfg_path_skills:   'Skills sidebar data source',
    cfg_path_ssh_log:  'SSH session temporary logs',
    cfg_close_btn:     'Close',

    // Feishu modal
    feishu_modal_title: '🔔 Feishu Bot Config',
    f_section_cred:    'App Credentials',
    f_section_status:  'Connection Status',
    f_status_disconnected: 'Disconnected',
    f_disconnect_btn:  'Disconnect',
    f_connect_btn:     'Save & Connect',
    f_section_bridge:  'Bridge Settings',
    f_delay_lbl:       'Reply Delay (s)',
    f_bridge_hint:     'Auto-create Claude session on connect, auto-close on disconnect',
    f_section_events:  'Recent Events',
    f_no_events:       'No events',
    f_events_update:   'Events will update continuously',
    f_close:           'Close',

    // Restart overlay
    restart_msg:       'Server Restarting...',
    spin_wait:         'Please wait',

    // Login page
    login_title:       '🐻 DruidClaw',
    login_prompt:      'Enter access token',
    login_token_ph:    'Access Token',
    login_btn:         'Login',

    // Status panel
    logs:              'Logs',
    server_logs:       'Server Logs',
    token_stats:       'Token Stats',
    trend:             'Trend',
    clear:             'Clear',
    auto_scroll:       'Auto scroll',
    no_logs:           'No logs',
    loading:           'Loading…',
    days:              'Days',
    total_input:       'Total Input Tokens',
    total_output:      'Total Output Tokens',
    total_cost:        'Total Cost',
    total_turns:       'Total Turns',
    sys_badge:         'System',
    user_badge:        'User',
    claude_badge:      'Claude',
    error_badge:       'Error',

    // Server/connection modal
    local_term:        'Local Shell',
    ssh_term:          'SSH Terminal',
    local_shell_label: 'Shell (optional, default $SHELL)',
    local_hint:        'Open a local terminal session directly, no SSH needed.',

    // Skills sidebar
    skills_title:      'Skills',
    prompts:           'Prompts',
    prompt_templates:  'Prompt Templates',
    history:           'History',
    history_tab:       'History',
    mcp_market:        'MCP Market',
    mcp_market_btn:    'MCP Market',
    prompt_btn:        'Prompt Templates',
    prompt_mgmt:       'Management',
    toggle_sidebar:    'Toggle Sidebar',
  }
};
let _lang = localStorage.getItem('cc_lang') || 'zh';

function t(key, params) {
  let val = (_i18n[_lang] && _i18n[_lang][key]) || (_i18n.zh[key]) || key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      val = val.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
    }
  }
  return val;
}

function applyLang() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = t(key);
    if (el.tagName === 'INPUT') {
      el.placeholder = val;
    } else if (val.includes('<')) {
      el.innerHTML = val;   // value contains HTML tags
    } else {
      el.textContent = val;
    }
  });
  // Update placeholders via data-i18n-ph
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  const langBtn = document.getElementById('lang-btn');
  if (langBtn) langBtn.textContent = _lang === 'zh' ? 'En' : '中';
  updateThemeButton();
  renderCards();
}

function toggleLang() {
  _lang = _lang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('cc_lang', _lang);
  applyLang();
}

// Translate system event messages (for IM bot system events)
function translateSystemEvent(summary) {
  if (_lang === 'zh') return summary;
  // English translations for common system messages
  const translations = {
    '已连接': 'Connected',
    '第': 'Attempt #',
    '次': '',
    '断开': 'Disconnected',
    '错误': 'Error',
    '连接失败': 'Connection failed',
    '运行错误': 'Runtime error',
    '已就绪': 'Ready',
    '多用户模式': 'multi-user mode',
    '基础名': 'base name',
    '已关闭所有用户会话': 'All user sessions closed',
    '已停止': 'Stopped',
    '事件': 'Event',
    '凭证验证成功': 'Credentials verified',
    '等待 Webhook 回调消息': 'waiting for webhook callback',
    '凭证验证失败': 'Credentials verification failed',
    'Token 无效': 'Invalid token',
    '轮询错误': 'Polling error',
    '已连接': 'Connected',
    '括号': '',
  };
  // Special handling for "已连接 (第 X 次)" pattern
  const connMatch = summary.match(/已连接 \(第 (\d+) 次\)/);
  if (connMatch) {
    return `Connected (attempt #${connMatch[1]})`;
  }
  // Special handling for "已就绪（多用户模式），基础名：XXX" pattern
  const readyMatch = summary.match(/已就绪（多用户模式），基础名：\s*(.+)/);
  if (readyMatch) {
    return `Ready (multi-user mode), base name: ${readyMatch[1]}`;
  }
  // General replacement for other patterns
  let result = summary;
  for (const [cn, en] of Object.entries(translations)) {
    result = result.split(cn).join(en);
  }
  return result;
}

// Translate install log messages
function translateInstallLog(msg) {
  if (_lang === 'zh') return msg;
  const translations = {
    '检查 nvm': 'Checking nvm...',
    '安装 nvm': 'Installing nvm...',
    'nvm 安装失败': 'nvm installation failed',
    '安装 Node.js LTS': 'Installing Node.js LTS...',
    'Node.js 安装失败': 'Node.js installation failed',
    '✓ nvm 已安装': '✓ nvm installed',
    '✓ Node.js 已安装': '✓ Node.js installed',
    '安装 Claude Code': 'Installing Claude Code...',
    '更新 Claude Code': 'Updating Claude Code...',
    'Claude Code 安装失败': 'Claude Code installation failed',
    '检查环境': 'Checking environment...',
    '未找到': 'Not found',
    '完成': 'Done',
    '错误': 'Error',
    '安装成功': 'Installation successful',
    '全部安装成功': 'All installations successful',
    '安装失败': 'Installation failed',
    '成功': 'Success',
    '失败': 'Failed',
  };
  let result = msg;
  for (const [cn, en] of Object.entries(translations)) {
    result = result.split(cn).join(en);
  }
  return result;
}

// ── Theme ─────────────────────────────────────────────────
let _currentTheme = localStorage.getItem('cc_theme') || 'auto';

// 获取系统主题偏好
function getSystemTheme() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// 获取当前主题（考虑自动模式）
function getEffectiveTheme() {
  if (_currentTheme === 'auto') {
    return getSystemTheme();
  }
  return _currentTheme;
}

// 应用主题
function applyTheme(theme) {
  _currentTheme = theme;
  const effectiveTheme = getEffectiveTheme();
  document.documentElement.classList.toggle('light', effectiveTheme === 'light');
  localStorage.setItem('cc_theme', theme);
  updateThemeButton();
  // Update xterm themes for any open terminals
  const srv = activeSrv();
  if (srv) {
    Object.values(srv.sessions).forEach(s => {
      if (s.term) {
        s.term.options.theme = _xtermTheme();
      }
    });
  }
}

function updateThemeButton() {
  const btn = document.getElementById('theme-btn');
  if (btn) {
    const icons = { dark: '🌙', light: '☀️', auto: '🌐' };
    btn.textContent = icons[_currentTheme] || icons.dark;
  }
}

function toggleTheme() {
  // Cycle through themes: dark -> light -> auto -> dark
  const themes = ['dark', 'light', 'auto'];
  const currentIndex = themes.indexOf(_currentTheme);
  const nextIndex = (currentIndex + 1) % themes.length;
  applyTheme(themes[nextIndex]);
}

// Listen for system theme changes
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (_currentTheme === 'auto') {
    applyTheme('auto');
  }
});

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
  const dropdown = document.getElementById('theme-dropdown');
  const btn = document.getElementById('theme-btn');
  if (dropdown && btn && !btn.contains(e.target) && !dropdown.contains(e.target)) {
    dropdown.classList.remove('show');
  }
});

function _xtermTheme() {
  const effectiveTheme = getEffectiveTheme();
  return effectiveTheme === 'dark'
    ? { background:'#0a0e1a', foreground:'#e8f1ff', cursor:'#00d4ff' }
    : { background:'#f0f4f8', foreground:'#1a2d3f', cursor:'#0066cc',
        selectionBackground:'#b0c4d8' };
}

// ── Status panel ─────────────────────────────────────────
let _logSeq = 0;
let _logNewCount = 0;
let _spOpen = false;
let _spActivePane = 'sp-log';
let _logPollTimer = null;
let _spChart = null;

function openStatusPanel() {
  _spOpen = true;
  _logNewCount = 0;
  _updateLogBadge();
  document.getElementById('status-panel-overlay').classList.add('show');
  spTab(_spActivePane);
  _logPollTick();
}

function closeStatusPanel(ev) {
  if (ev && ev.target !== document.getElementById('status-panel-overlay')) return;
  _spOpen = false;
  clearTimeout(_logPollTimer);
  document.getElementById('status-panel-overlay').classList.remove('show');
}

function spTab(pane) {
  _spActivePane = pane;
  document.querySelectorAll('.sp-tab').forEach(t => t.classList.toggle('active', t.dataset.pane === pane));
  document.querySelectorAll('.sp-pane').forEach(p => p.classList.toggle('active', p.id === pane));
  if (pane === 'sp-stats') spLoadStats();
  if (pane === 'sp-trend') spLoadTrend();
}

function spLogClear() {
  document.getElementById('sp-log-entries').innerHTML =
    `<div style="padding:14px;color:var(--muted);text-align:center;font-size:12px">${t('no_logs')}</div>`;
}

function _updateLogBadge() {
  const badge = document.getElementById('log-badge');
  if (!badge) return;
  if (_logNewCount > 0) {
    badge.textContent = _logNewCount > 99 ? '99+' : String(_logNewCount);
    badge.classList.add('show');
  } else {
    badge.classList.remove('show');
  }
}

async function _logPollTick() {
  try {
    const r = await fetch(`/api/log?after=${_logSeq}`);
    const d = await r.json();
    if (d.entries && d.entries.length) {
      _logSeq = d.latest_seq;
      const visible = d.entries.filter(e => e.level !== 'DEBUG');
      if (!_spOpen) {
        _logNewCount += visible.length;
        _updateLogBadge();
      } else if (_spActivePane === 'sp-log') {
        _spAppendLogs(visible);
      } else {
        _logNewCount += visible.length;
        _updateLogBadge();
      }
    }
    // Update log count display
    const cnt = document.getElementById('sp-log-count');
    if (cnt) cnt.textContent = `seq: ${d.latest_seq}`;
  } catch (_) {}
  if (_spOpen) {
    _logPollTimer = setTimeout(_logPollTick, 2000);
  }
}

function _spAppendLogs(entries) {
  const el = document.getElementById('sp-log-entries');
  if (!el) return;
  el.querySelectorAll('div[style]').forEach(e => e.remove());
  for (const e of entries) {
    const row = document.createElement('div');
    row.className = 'sp-log-entry';
    row.innerHTML =
      `<span class="sp-log-ts">${e.ts}</span>` +
      `<span class="sp-log-lvl ${e.level}">${e.level}</span>` +
      `<span class="sp-log-msg">${esc(e.msg)}</span>`;
    el.appendChild(row);
  }
  while (el.children.length > 300) el.removeChild(el.firstChild);
  const autoEl = document.getElementById('sp-log-auto');
  if (autoEl && autoEl.checked) el.scrollTop = el.scrollHeight;
}

async function spLoadStats() {
  const grid = document.getElementById('sp-stats-grid');
  if (!grid) return;
  grid.innerHTML = `<div style="grid-column:1/-1;padding:20px;text-align:center;color:var(--muted)">${t('loading')}</div>`;
  try {
    const r = await fetch('/api/stats/global');
    const d = await r.json();
    const tk = d.total || {};
    const fmtN = n => n >= 1e6 ? `${(n/1e6).toFixed(2)}M`
                    : n >= 1e3 ? `${(n/1e3).toFixed(1)}k` : String(n||0);
    grid.innerHTML = `
      <div class="sp-stat-cell blue">
        <div class="sc-label">${t('total_input')}</div>
        <div class="sc-val">${fmtN(tk.input)}</div>
        <div class="sc-sub">缓存读 ${fmtN(tk.cache_read)}</div>
      </div>
      <div class="sp-stat-cell green">
        <div class="sc-label">${t('total_output')}</div>
        <div class="sc-val">${fmtN(tk.output)}</div>
        <div class="sc-sub">缓存写 ${fmtN(tk.cache_creation)}</div>
      </div>
      <div class="sp-stat-cell yellow">
        <div class="sc-label">${t('total_cost')}</div>
        <div class="sc-val">${d.cost_usd > 0 ? '$'+d.cost_usd.toFixed(3) : '—'}</div>
        <div class="sc-sub">USD 估算</div>
      </div>
      <div class="sp-stat-cell">
        <div class="sc-label">${t('total_turns')}</div>
        <div class="sc-val">${d.turns||0}</div>
        <div class="sc-sub">${d.files||0} 个会话文件</div>
      </div>
    `;
  } catch (e) {
    grid.innerHTML = `<div style="grid-column:1/-1;padding:20px;color:var(--red)">${esc(e.message)}</div>`;
  }
}

async function spLoadTrend() {
  const days = parseInt(document.getElementById('sp-trend-days')?.value || '14');
  try {
    const r = await fetch(`/api/stats/trend?days=${days}`);
    const d = await r.json();
    const canvas = document.getElementById('sp-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (_spChart) { _spChart.destroy(); _spChart = null; }
    _spChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: d.days || [],
        datasets: [
          {
            label: '输入 Token',
            data: d.input || [],
            borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,.1)',
            tension: 0.3, fill: true,
          },
          {
            label: '输出 Token',
            data: d.output || [],
            borderColor: '#3fb950', backgroundColor: 'rgba(63,185,80,.1)',
            tension: 0.3, fill: true,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#8b949e' } } },
        scales: {
          x: { ticks: { color: '#8b949e' }, grid: { color: '#30363d' } },
          y: { ticks: { color: '#8b949e' }, grid: { color: '#30363d' } },
        },
      },
    });
  } catch (e) {
    console.warn('Trend chart error:', e);
  }
}

// 后台日志轮询（保持角标更新）
async function _bgLogPoll() {
  try {
    const r = await fetch(`/api/log?after=${_logSeq}`);
    const d = await r.json();
    if (d.entries && d.entries.length) {
      _logSeq = d.latest_seq;
      const newEntries = d.entries.filter(e => e.level !== 'DEBUG');
      if (_spOpen && _spActivePane === 'sp-log') {
        _spAppendLogs(newEntries);
      } else if (newEntries.length) {
        _logNewCount += newEntries.length;
        _updateLogBadge();
      }
    }
  } catch (_) {}
  setTimeout(_bgLogPoll, 4000);
}

// ── Resize ────────────────────────────────────────────────
let _rtimer;
window.addEventListener('resize', () => {
  clearTimeout(_rtimer);
  _rtimer = setTimeout(() => {
    const srv = activeSrv();
    if (srv && srv.activeSession) safeFit(srv, srv.activeSession);
  }, 100);
});

// ── Toast ─────────────────────────────────────────────────
let _ttimer;
// 显示 Toast 消息
function toast(msg, isErr = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.borderColor = isErr ? 'var(--red)' : 'var(--border)';
  el.classList.add('show');
  clearTimeout(_ttimer);
  _ttimer = setTimeout(() => el.classList.remove('show'), 3000);
}

// ── Keyboard shortcuts ────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('srv-modal').classList.remove('show');
    document.getElementById('cfg-modal').classList.remove('show');
    document.getElementById('new-card-modal').classList.remove('show');
    document.getElementById('stats-overlay').classList.remove('show');
    closeStatusPanel();
    document.getElementById('install-overlay')?.classList.remove('show');
    document.getElementById('mkt-overlay')?.classList.remove('show');
    if (document.getElementById('feishu-overlay').classList.contains('show')) {
      document.getElementById('feishu-overlay').classList.remove('show');
      _stopFeishuPoll();
    }
  }
  // Enter in server modal
  if (e.key === 'Enter' && document.getElementById('srv-modal').classList.contains('show')) commitServer();
});

// Refresh status every 8s: cards + feishu badge
setInterval(async () => {
  try {
    const r = await fetch('/api/feishu/status');
    _fpApplyStatus(await r.json());
  } catch (_) {}
}, 8000);

// ── Init ──────────────────────────────────────────────────
// 初始化左侧边栏拖动调整大小
function initSidebarResize() {
  const handle = document.getElementById('sidebar-resize');
  const sidebar = document.getElementById('sidebar');
  if (!handle || !sidebar) return;

  let isResizing = false;
  let startX = 0;
  let startWidth = 0;

  const onMouseDown = (e) => {
    isResizing = true;
    startX = e.clientX;
    startWidth = sidebar.offsetWidth;
    handle.classList.add('resizing');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const onMouseMove = (e) => {
    if (!isResizing) return;
    const delta = e.clientX - startX;
    const newWidth = Math.max(150, Math.min(500, startWidth + delta));
    sidebar.style.width = newWidth + 'px';
  };

  const onMouseUp = () => {
    if (isResizing) {
      isResizing = false;
      handle.classList.remove('resizing');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      // Save to localStorage
      localStorage.setItem('sidebar-width', sidebar.style.width);
    }
  };

  handle.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);

  // Restore from localStorage
  const savedWidth = localStorage.getItem('sidebar-width');
  if (savedWidth) sidebar.style.width = savedWidth;
}

// 初始化右侧边栏拖动调整大小
function initRightSidebarResize() {
  const handle = document.getElementById('right-sidebar-resize');
  const sidebar = document.getElementById('skills-sidebar');
  if (!handle || !sidebar) {
    console.warn('Right sidebar resize: handle or sidebar not found');
    return;
  }

  let isResizing = false;
  let startX = 0;
  let startWidth = 0;
  const DEFAULT_WIDTH = 190;

  const onMouseDown = (e) => {
    e.preventDefault();
    isResizing = true;
    startX = e.clientX;
    startWidth = sidebar.offsetWidth;
    handle.classList.add('resizing');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const onMouseMove = (e) => {
    if (!isResizing) return;
    e.preventDefault();
    const delta = startX - e.clientX;
    const newWidth = Math.max(0, Math.min(500, startWidth + delta));
    sidebar.style.width = newWidth + 'px';
  };

  const onMouseUp = () => {
    if (isResizing) {
      isResizing = false;
      handle.classList.remove('resizing');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      const finalWidth = parseInt(sidebar.style.width) || 0;
      if (finalWidth <= 0) {
        const savedWidth = localStorage.getItem('right-sidebar-width');
        sidebar.style.width = savedWidth ? savedWidth : DEFAULT_WIDTH + 'px';
      } else {
        localStorage.setItem('right-sidebar-width', sidebar.style.width);
      }
    }
  };

  handle.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);

  // Restore from localStorage
  const savedWidth = localStorage.getItem('right-sidebar-width');
  if (savedWidth) sidebar.style.width = savedWidth;
}

window.addEventListener('load', async () => {
  // 先尝试恢复之前的会话
  await restoreSessionsFromStorage();

  // 如果没有恢复会话，才添加默认服务器
  if (servers.length === 0) {
    const selfHost = location.hostname;
    const selfPort = parseInt(location.port) || 19123;
    const id = await addServer(selfHost, selfPort, `${selfHost}:${selfPort}`);
  }

  // 初始化侧边栏拖动调整大小
  initSidebarResize();
  initRightSidebarResize();

  const srv = activeSrv();

  // Apply theme and language
  applyTheme(_currentTheme);
  applyLang();
  // Start background log polling (badge updates even when panel closed)
  _bgLogPoll();
  // Load cards from backend (await so we can act on them immediately)
  await loadCards();
  startCardPoll();
  loadSkills();
});

// ── Scheduled tasks ────────────────────────────────────────
let _tasks = [];
let _editingTaskId = null;

// 打开任务模态框
async function openTasksModal() {
  document.getElementById('tasks-modal').classList.add('show');
  cancelAddTask();
  await loadTasks();
  // Populate session datalist
  const dl = document.getElementById('tf-session-list');
  dl.innerHTML = '';
  for (const c of _cards.filter(c => c.type === 'claude')) {
    const opt = document.createElement('option');
    opt.value = c.name;
    dl.appendChild(opt);
  }
}

// 关闭任务模态框
function closeTasksModal(ev) {
  if (ev && ev.target !== document.getElementById('tasks-modal')) return;
  document.getElementById('tasks-modal').classList.remove('show');
}

// 加载任务列表
async function loadTasks() {
  try {
    const r = await fetch('/api/tasks');
    const d = await r.json();
    _tasks = d.tasks || [];
    renderTaskList();
  } catch (_) {}
}

// 渲染任务列表
function renderTaskList() {
  const list = document.getElementById('task-list');
  if (!_tasks.length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:16px">暂无定时任务</div>';
    return;
  }
  list.innerHTML = '';
  for (const t of _tasks) {
    const schedLabel = t.schedule_type === 'cron'
      ? `Cron: <code>${esc(t.cron_expr)}</code>`
      : `每 ${t.interval_minutes} 分钟`;
    const lastRun = t.last_run
      ? `上次: ${t.last_run} · 共运行 ${t.run_count} 次`
      : '尚未运行';
    const row = document.createElement('div');
    row.className = 'task-row' + (t.enabled ? '' : ' task-disabled');
    row.innerHTML = `
      <div class="task-info">
        <div class="task-name">${esc(t.name)}</div>
        <div class="task-prompt">→ <b>${esc(t.session_name)}</b>: ${esc(t.prompt)}</div>
        <div class="task-meta">
          <span>${schedLabel}</span>
          <span>${lastRun}</span>
          <span style="color:${t.enabled?'var(--green)':'var(--muted)'}">●&nbsp;${t.enabled?'启用':'禁用'}</span>
        </div>
      </div>
      <div class="task-btns">
        <button class="mbtn" onclick="runTaskNow('${t.id}')" title="立即触发一次">▶</button>
        <button class="mbtn" onclick="toggleTask('${t.id}',${!t.enabled})" title="${t.enabled?'禁用':'启用'}">${t.enabled?'⏸':'▶'}</button>
        <button class="mbtn" onclick="editTask('${t.id}')" title="编辑">✏</button>
        <button class="mbtn" style="color:var(--red)" onclick="deleteTask('${t.id}')" title="删除">✕</button>
      </div>`;
    list.appendChild(row);
  }
}

// 打开新建任务表单
function openAddTask() {
  _editingTaskId = null;
  document.getElementById('task-form-title').textContent = '新建任务';
  document.getElementById('tf-id').value       = '';
  document.getElementById('tf-name').value     = '';
  document.getElementById('tf-session').value  = '';
  document.getElementById('tf-prompt').value   = '';
  document.getElementById('tf-interval').value = '60';
  document.getElementById('tf-cron').value     = '0 * * * *';
  document.querySelectorAll('input[name="tf-stype"]')[0].checked = true;
  tfScheduleType('interval');
  document.getElementById('task-form').style.display = '';
}

// 编辑任务
function editTask(id) {
  const t = _tasks.find(x => x.id === id);
  if (!t) return;
  _editingTaskId = id;
  document.getElementById('task-form-title').textContent = '编辑任务';
  document.getElementById('tf-id').value       = t.id;
  document.getElementById('tf-name').value     = t.name;
  document.getElementById('tf-session').value  = t.session_name;
  document.getElementById('tf-prompt').value   = t.prompt;
  document.getElementById('tf-interval').value = t.interval_minutes;
  document.getElementById('tf-cron').value     = t.cron_expr || '0 * * * *';
  const stype = t.schedule_type || 'interval';
  document.querySelectorAll('input[name="tf-stype"]').forEach(r => r.checked = (r.value === stype));
  tfScheduleType(stype);
  document.getElementById('task-form').style.display = '';
}

// 取消新建任务
function cancelAddTask() {
  _editingTaskId = null;
  document.getElementById('task-form').style.display = 'none';
}

// 切换任务类型（interval/cron）
function tfScheduleType(type) {
  document.getElementById('tf-interval-f').style.display = type === 'interval' ? '' : 'none';
  document.getElementById('tf-cron-f').style.display     = type === 'cron'     ? '' : 'none';
}

// 提交保存任务
async function submitTask() {
  const stype = document.querySelector('input[name="tf-stype"]:checked')?.value || 'interval';
  const payload = {
    name:             document.getElementById('tf-name').value.trim(),
    session_name:     document.getElementById('tf-session').value.trim(),
    prompt:           document.getElementById('tf-prompt').value,
    schedule_type:    stype,
    interval_minutes: parseInt(document.getElementById('tf-interval').value) || 60,
    cron_expr:        document.getElementById('tf-cron').value.trim() || '0 * * * *',
  };
  if (!payload.session_name) { toast('请填写目标 Session', true); return; }
  if (!payload.prompt.trim()) { toast('提词内容不能为空', true); return; }
  try {
    const url    = _editingTaskId ? `/api/tasks/${_editingTaskId}` : '/api/tasks';
    const method = _editingTaskId ? 'PATCH' : 'POST';
    const r = await fetch(url, { method, headers: {'Content-Type':'application/json'},
                                  body: JSON.stringify(payload) });
    if (!r.ok) { const d = await r.json(); throw new Error(d.detail||'保存失败'); }
    cancelAddTask();
    await loadTasks();
    toast(_editingTaskId ? '任务已更新' : '任务已创建');
  } catch (e) { toast(e.message, true); }
}

// 删除任务
async function deleteTask(id) {
  if (!confirm('确认删除该定时任务？')) return;
  await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
  await loadTasks();
  toast('任务已删除');
}

// 切换任务启用状态
async function toggleTask(id, enable) {
  await fetch(`/api/tasks/${id}`, { method: 'PATCH',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ enabled: enable }) });
  await loadTasks();
}

// 立即运行任务
async function runTaskNow(id) {
  const r = await fetch(`/api/tasks/${id}/run`, { method: 'POST' });
  if (r.ok) toast('已触发任务');
}

// 退出登录
async function doLogout() {
  await fetch('/logout', { method: 'POST' });
  window.location.href = '/login';
}

// ── Prompt templates ──────────────────────────────────────
let _prompts = [];
let _promptEditId = null;

// 加载提示词模板
async function loadPrompts() {
  try {
    const r = await fetch('/api/prompts');
    _prompts = (await r.json()).prompts || [];
    renderPrompts(_prompts);
    renderPromptMgmtList(_prompts);
  } catch (_) {}
}

// ── Prompt管理 modal (header button) ──────────────────────
// 打开提示词管理模态框
async function openPromptMgmt() {
  document.getElementById('prompt-mgmt-overlay').classList.add('show');
  await loadPrompts();
  resetPromptForm();
}

// 关闭提示词管理模态框
function closePromptMgmt(ev) {
  if (ev && ev.target !== document.getElementById('prompt-mgmt-overlay')) return;
  document.getElementById('prompt-mgmt-overlay').classList.remove('show');
}

function filterPromptMgmt() {
  const q = document.getElementById('pm-search').value.toLowerCase();
  renderPromptMgmtList(q ? _prompts.filter(p =>
    p.name.toLowerCase().includes(q) || p.prompt.toLowerCase().includes(q)
  ) : _prompts);
}

function renderPromptMgmtList(list) {
  const el = document.getElementById('pm-list');
  if (!list.length) {
    el.innerHTML = '<div style="font-size:12px;color:var(--muted);padding:12px 4px">暂无模板</div>';
    return;
  }
  el.innerHTML = '';
  for (const p of list) {
    const div = document.createElement('div');
    div.className = 'mkt-card';
    if (_promptEditId === p.id) div.classList.add('installed');
    div.innerHTML =
      `<div class="mkt-card-name">${esc(p.name)}</div>` +
      `<div class="mkt-card-desc" style="-webkit-line-clamp:2">${esc(p.prompt)}</div>` +
      `<div class="mkt-card-actions" style="margin-top:8px">
        <button class="mkt-btn primary" onclick="editPrompt('${p.id}')">编辑</button>
        <button class="mkt-btn" onclick="deletePrompt('${p.id}')">删除</button>
      </div>`;
    el.appendChild(div);
  }
}

function editPrompt(id) {
  _promptEditId = id;
  const p = _prompts.find(x => x.id === id);
  document.getElementById('pm-form-title').textContent = '编辑模板';
  document.getElementById('pe-name').value   = p ? p.name   : '';
  document.getElementById('pe-prompt').value = p ? p.prompt : '';
  renderPromptMgmtList(_prompts);
  document.getElementById('pe-name').focus();
}

function resetPromptForm() {
  _promptEditId = null;
  document.getElementById('pm-form-title').textContent = '新建模板';
  document.getElementById('pe-name').value   = '';
  document.getElementById('pe-prompt').value = '';
}

async function savePrompt() {
  const name   = document.getElementById('pe-name').value.trim();
  const prompt = document.getElementById('pe-prompt').value.trim();
  if (!name || !prompt) { toast('名称和内容不能为空', true); return; }
  const st = document.getElementById('pm-status');
  try {
    const url    = _promptEditId ? `/api/prompts/${_promptEditId}` : '/api/prompts';
    const method = _promptEditId ? 'PATCH' : 'POST';
    const r = await fetch(url, { method, headers: {'Content-Type':'application/json'},
                                  body: JSON.stringify({ name, prompt }) });
    if (!r.ok) throw new Error((await r.json()).detail || '保存失败');
    st.textContent = _promptEditId ? `✅ "${name}" 已更新` : `✅ "${name}" 已创建`;
    resetPromptForm();
    await loadPrompts();
  } catch (e) { st.textContent = '❌ ' + e.message; }
}

async function deletePrompt(id) {
  if (!confirm('确认删除该模板？')) return;
  await fetch(`/api/prompts/${id}`, { method: 'DELETE' });
  if (_promptEditId === id) resetPromptForm();
  await loadPrompts();
  toast(t('toast_deleted'));
}

// ── 右侧栏 Prompt 面板（使用） ─────────────────────────────
// 筛选提示词（搜索）
function filterPrompts() {
  const q = document.getElementById('prompt-search').value.toLowerCase();
  renderPrompts(q ? _prompts.filter(p =>
    p.name.toLowerCase().includes(q) || p.prompt.toLowerCase().includes(q)
  ) : _prompts);
}

// 渲染提示词列表
function renderPrompts(list) {
  const el = document.getElementById('prompt-list');
  if (!el) return;
  if (!list.length) {
    el.innerHTML = '<div class="skills-empty">' + t('no_templates') + '</div>';
    return;
  }
  el.innerHTML = '';
  for (const p of list) {
    const div = document.createElement('div');
    div.className = 'prompt-item';
    div.title = p.prompt;
    div.innerHTML = `<div class="p-name">${esc(p.name)}</div><div class="p-preview">${esc(p.prompt)}</div>`;
    div.addEventListener('click', () => insertPrompt(p.prompt));
    el.appendChild(div);
  }
}

// 插入提示词到当前会话
function insertPrompt(text) {
  const srv = activeSrv();
  if (!srv || !srv.activeSession) { toast('请先连接一个 Claude 会话', true); return; }
  const s = srv.sessions[srv.activeSession];
  if (!s || !s.ws || s.ws.readyState !== WebSocket.OPEN) { toast('会话未连接', true); return; }
  const bytes = new TextEncoder().encode(text);
  s.ws.send(JSON.stringify({ type: 'input', data: btoa(String.fromCharCode(...bytes)) }));
  if (s.term) s.term.focus();
}

// ── MCP Market ────────────────────────────────────────────────
let _mcpData = { servers: {}, presets: [] };

// 打开 MCP 市场模态框
async function openMcpModal() {
  document.getElementById('mcp-overlay').classList.add('show');
  await loadMcpData();
}

// 关闭 MCP 市场模态框
function closeMcpModal(ev) {
  if (ev && ev.target !== document.getElementById('mcp-overlay')) return;
  document.getElementById('mcp-overlay').classList.remove('show');
}

// 加载 MCP 数据
async function loadMcpData() {
  try {
    const r = await fetch('/api/mcp');
    _mcpData = await r.json();
    renderMcpInstalled();
    renderMcpPresets();
  } catch (e) {
    document.getElementById('mcp-status').textContent = '加载失败: ' + e.message;
  }
}

// 渲染已安装的 MCP 服务器
function renderMcpInstalled() {
  const list = document.getElementById('mcp-installed-list');
  const servers = _mcpData.servers || {};
  const names = Object.keys(servers);
  if (!names.length) {
    list.innerHTML = '<div style="font-size:12px;color:var(--muted)">暂无</div>';
    return;
  }
  list.innerHTML = names.map(n =>
    `<div style="display:flex;align-items:center;gap:4px;padding:4px 6px;background:var(--bg3);border-radius:6px;font-size:12px">
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(JSON.stringify(servers[n]))}">${esc(n)}</span>
      <button class="mkt-btn" onclick="mcpRemove('${esc(n)}')" style="padding:1px 6px;font-size:11px;color:var(--red)">✕</button>
    </div>`
  ).join('');
}

// 渲染 MCP 预设列表
function renderMcpPresets() {
  const grid = document.getElementById('mcp-preset-grid');
  const installed = new Set(Object.keys(_mcpData.servers || {}));
  grid.innerHTML = (_mcpData.presets || []).map(p => {
    const ok = installed.has(p.key);
    return `<div class="mkt-card${ok?' installed':''}">
      <div class="mkt-card-name">${esc(p.label)}${ok?'<span class="installed-badge">已安装</span>':''}</div>
      <div class="mkt-card-desc">${esc(p.desc)}</div>
      <div class="mkt-card-actions" style="margin-top:8px">
        ${ok
          ? `<button class="mkt-btn" onclick="mcpRemove('${esc(p.key)}')">卸载</button>`
          : `<button class="mkt-btn primary" onclick="mcpInstallPreset(${esc(JSON.stringify(p))})">安装</button>`
        }
        <button class="mkt-btn" onclick="mcpCopyCmd(${esc(JSON.stringify(p))})" title="复制命令">📋</button>
      </div>
    </div>`;
  }).join('');
}

// 安装 MCP 预设
async function mcpInstallPreset(preset) {
  const st = document.getElementById('mcp-status');
  st.textContent = `安装 ${preset.label}…`;
  try {
    const r = await fetch('/api/mcp', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name: preset.key, command: preset.command, args: preset.args, env: preset.env || {} }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || '失败');
    st.textContent = `✅ ${preset.label} 已添加到 ~/.claude.json`;
    await loadMcpData();
  } catch (e) { st.textContent = '❌ ' + e.message; }
}

async function mcpRemove(name) {
  if (!confirm(`确认移除 MCP 服务 "${name}"？`)) return;
  const st = document.getElementById('mcp-status');
  try {
    await fetch(`/api/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' });
    st.textContent = `✅ "${name}" 已移除`;
    await loadMcpData();
  } catch (e) { st.textContent = '❌ ' + e.message; }
}

function _parseArgs(raw) {
  // Shell-like split: respects "quoted args" and 'single quotes'
  const args = []; let cur = ''; let inQ = '';
  for (const ch of raw) {
    if (inQ) { if (ch === inQ) inQ = ''; else cur += ch; }
    else if (ch === '"' || ch === "'") { inQ = ch; }
    else if (/\s/.test(ch)) { if (cur) { args.push(cur); cur = ''; } }
    else cur += ch;
  }
  if (cur) args.push(cur);
  return args;
}

async function mcpAddCustom() {
  const name    = document.getElementById('mcp-add-name').value.trim();
  const command = document.getElementById('mcp-add-command').value.trim();
  const argsRaw = document.getElementById('mcp-add-args').value.trim();
  const envRaw  = document.getElementById('mcp-add-env').value.trim();
  if (!name || !command) { toast('名称和命令不能为空', true); return; }
  let args = argsRaw ? _parseArgs(argsRaw) : [];
  let env = {};
  if (envRaw) { try { env = JSON.parse(envRaw); } catch { toast('环境变量 JSON 格式错误', true); return; } }
  const st = document.getElementById('mcp-status');
  try {
    const r = await fetch('/api/mcp', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, command, args, env }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || '失败');
    ['mcp-add-name','mcp-add-command','mcp-add-args','mcp-add-env'].forEach(id =>
      document.getElementById(id).value = '');
    st.textContent = `✅ "${name}" 已添加`;
    await loadMcpData();
  } catch (e) { st.textContent = '❌ ' + e.message; }
}

// ── History page ──────────────────────────────────────────
let _histLogs = [];
let _histSummaries = {};  // log_file → summary entry
let _histSelected = null;

async function histLoad() {
  const [logsResp, sumsResp] = await Promise.all([
    fetch('/api/history/logs'),
    fetch('/api/history/summaries'),
  ]);
  const logsData = await logsResp.json();
  const sumsData = await sumsResp.json();

  _histLogs = logsData.logs || [];
  _histSummaries = {};
  for (const s of (sumsData.summaries || [])) {
    _histSummaries[s.log_file] = s;
  }
  histRenderList();
  if (_histSelected) histShowDetail(_histSelected);
}

function histRefresh() { histLoad(); }

function histRenderList() {
  const el = document.getElementById('hist-list');
  if (!_histLogs.length) {
    el.innerHTML = '<div class="hist-empty">暂无日志文件</div>';
    return;
  }
  el.innerHTML = _histLogs.map(log => {
    const hasSummary = !!_histSummaries[log.name];
    const active = _histSelected === log.name ? ' active' : '';
    const summarized = hasSummary ? ' has-summary' : '';
    const sizeKB = (log.size / 1024).toFixed(1);
    return `<div class="hist-item${active}${summarized}" onclick="histSelect('${log.name}')">
      <div class="hist-name">${hasSummary ? '✅ ' : ''}${log.name}</div>
      <div class="hist-meta"><span>${log.mtime_str}</span><span>${sizeKB} KB</span></div>
    </div>`;
  }).join('');
}

function histSelect(name) {
  _histSelected = name;
  histRenderList();
  histShowDetail(name);
}

function histShowDetail(name) {
  const detail = document.getElementById('hist-detail');
  const log = _histLogs.find(l => l.name === name);
  if (!log) { detail.innerHTML = '<div class="hist-empty">找不到该文件</div>'; return; }

  const summary = _histSummaries[name];
  if (summary) {
    detail.innerHTML = `
      <div class="hist-summary-card">
        <div class="hist-summary-hdr">
          <h4>📋 ${name}</h4>
          <span style="font-size:11px;color:var(--muted)">${summary.created_at.replace('T',' ').slice(0,16)} · ${summary.model}</span>
          <button class="mbtn danger" onclick="histDeleteSummary('${summary.id}','${name}')" style="font-size:11px;padding:2px 8px">删除</button>
          <button class="mbtn" onclick="histGenerate('${name}')" style="font-size:11px;padding:2px 8px">重新生成</button>
        </div>
        <div class="hist-summary-body">${escapeHtml(summary.summary)}</div>
      </div>`;
  } else {
    detail.innerHTML = `
      <div class="hist-generate-wrap">
        <div>📄 <strong>${name}</strong></div>
        <div style="color:var(--muted)">${log.mtime_str} · ${(log.size/1024).toFixed(1)} KB</div>
        <div>尚未生成总结</div>
        <button class="cbtn ok" onclick="histGenerate('${name}')">✨ 生成 AI 总结</button>
      </div>`;
  }
}

async function histGenerate(name) {
  const detail = document.getElementById('hist-detail');
  detail.innerHTML = `<div class="hist-generate-wrap"><div>⏳ 正在调用 AI 生成总结，请稍候…</div></div>`;
  try {
    const r = await fetch('/api/history/generate', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ log_file: name }),
    });
    if (!r.ok) {
      const err = await r.json();
      throw new Error(err.detail || '生成失败');
    }
    const entry = await r.json();
    _histSummaries[name] = entry;
    histRenderList();
    histShowDetail(name);
    toast('总结生成成功');
  } catch (e) {
    detail.innerHTML = `<div class="hist-generate-wrap" style="color:var(--red)">❌ ${e.message}<br><br><button class="cbtn ok" onclick="histGenerate('${name}')">重试</button></div>`;
  }
}

async function histDeleteSummary(id, name) {
  if (!confirm('删除此总结？')) return;
  await fetch(`/api/history/${id}`, { method: 'DELETE' });
  delete _histSummaries[name];
  histRenderList();
  histShowDetail(name);
  toast('总结已删除');
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function mcpCopyCmd(preset) {
  const cmd = [preset.command, ...preset.args].join(' ');
  navigator.clipboard.writeText(cmd).then(() => toast('命令已复制'));
}
