"""
Feishu/IM ↔ Claude bridge logic.

Contains:
  - ANSI/text cleaning utilities
  - _UserSessionPool: per-user Claude session management
  - _ReplyCollector: PTY output collection and IM reply dispatch
  - IM event handlers for all platforms
  - Bot start/stop/get helpers for all platforms
"""
import re as _re
import json
import time
import hashlib
import threading
import tempfile as _tempfile
import collections as _collections
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path

from druidclaw.core.session import ClaudeSession
from druidclaw.imbot.feishu import FeishuBot
from druidclaw.imbot.telegram import TelegramBot
from druidclaw.imbot.dingtalk import DingtalkBot
from druidclaw.imbot.qq import QQBot
from druidclaw.imbot.wework import WeWorkBot

from druidclaw.web.state import (
    RUN_DIR,
    _feishu_bots, _feishu_lock,
    _telegram_bots, _telegram_lock,
    _dingtalk_bots, _dingtalk_lock,
    _qq_bots, _qq_lock,
    _wework_bots, _wework_lock,
    BRIDGE_CONFIG_FILE, _bridge_cfg, _bridge_cfg_lock,
    _sched_tasks, _sched_lock,
    _load_feishu_config,
)

logger = logging.getLogger(__name__)

# ── Bridge config helpers ─────────────────────────────────────────

def _load_bridge_config() -> dict:
    if BRIDGE_CONFIG_FILE.exists():
        try:
            data = json.loads(BRIDGE_CONFIG_FILE.read_text())
            with _bridge_cfg_lock:
                _bridge_cfg["reply_delay"] = float(data.get("reply_delay", 2.0))
        except Exception:
            pass
    return dict(_bridge_cfg)


def _save_bridge_config():
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with _bridge_cfg_lock:
        BRIDGE_CONFIG_FILE.write_text(json.dumps(_bridge_cfg, indent=2))


# ── ANSI / text cleaning ──────────────────────────────────────────

# Single combined regex for all ANSI/control char cleaning in one pass
# Merges _ANSI_RE, _CTRL_RE, and sync marker handling
_ANSI_CLEAN_RE = _re.compile(
    r'\x1b\[\?2026[hl]'              # sync blocks → replaced with \n specially
    r'|\x1b\[[\x20-\x3f]*[\x40-\x7e]'  # CSI (incl. private: ?2026h/l, etc.)
    r'|\x1b[()][AB012]'                # charset designation
    r'|\x1b[=>]'                       # alt/normal keypad
    r'|\x1b[DEHMNOPQRSTUVWXYZ\\^_`abcdfghijklnopqrstuvwxyz{|}~]'  # Fe
    r'|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC (window title, etc.)
    r'|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\r]'  # control chars + CR
)


# Lines that are Claude Code's TUI chrome (not the actual response)
_CLAUDE_UI_LINE_RE = _re.compile(
    r'^[\s⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏●○◆◇▸▹►▻✦✔✗⣾⣽⣻⢿⡿⣟⣯⣷]*$'   # spinner-only lines
    r'|^[\s⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏●]\s*(Thinking|Loading|Working|Running|Processing)\.{0,3}\s*$'
    r'|ctrl\+[a-z]'     # keyboard shortcuts (toolbar)
    r'|^─+$'            # separator lines
    r'|VSCode|GitLens'  # IDE integration hints
    , _re.IGNORECASE
)

# Claude Code footer state detection (matched after ANSI-strip + space-removal)
# Working: Claude is thinking / executing tools — do NOT flush yet
# Idle:    Claude finished, waiting for next message — flush soon
_WORKING_RE = _re.compile(r'esctointerrupt', _re.IGNORECASE)
_IDLE_RE    = _re.compile(
    r'\?forshortcuts'       # normal mode
    r'|planmodeon'          # plan mode
    r'|accepteditson',      # auto-edit mode
    _re.IGNORECASE
)


def _clean_output(raw: str, skip_echo: str = "") -> str:
    """
    Convert raw PTY output to clean Feishu-sendable text:
    1. Treat synchronized-output blocks (\x1b[?2026h..l) as line separators
    2. Strip all ANSI escape sequences and control chars in single pass
    3. Deduplicate consecutive blank lines
    4. Skip input echo line (first occurrence)
    5. Skip known Claude TUI chrome lines
    """
    # Single-pass cleaning: sync markers → \n, everything else → ''
    def _replace(match):
        m = match.group(0)
        return '\n' if m == '\x1b[?2026h' or m == '\x1b[?2026l' else ''

    text = _ANSI_CLEAN_RE.sub(_replace, raw)
    lines = text.split('\n')
    out = []
    prev_blank = False
    echo = skip_echo.strip()
    for line in lines:
        line = line.rstrip()
        # Skip input echo (first occurrence only)
        if echo and line.strip() == echo:
            echo = ""
            continue
        # Skip Claude TUI chrome
        if _CLAUDE_UI_LINE_RE.search(line):
            continue
        if not line:
            if prev_blank:
                continue  # collapse multiple blanks
            prev_blank = True
        else:
            prev_blank = False
        out.append(line)
    return '\n'.join(out).strip()


def _split_message(text: str, max_chars: int = 4000) -> list[str]:
    """
    Split a long text into chunks of at most max_chars characters.
    Splits at paragraph boundaries first, then line boundaries, then hard-cuts.
    Returns a list of strings; single-chunk results have no label added.
    Multi-chunk results are labelled (1/N) … (N/N) at the end of each chunk.
    """
    if len(text) <= max_chars:
        return [text]

    # Try to split at double-newline (paragraph) boundaries
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        # A single paragraph may itself exceed max_chars → split by lines
        if len(para) > max_chars:
            lines = para.split("\n")
            for line in lines:
                # A single line may exceed max_chars → hard-cut
                while len(line) > max_chars:
                    if current:
                        chunks.append(current.rstrip())
                        current = ""
                    chunks.append(line[:max_chars])
                    line = line[max_chars:]
                candidate = (current + "\n" + line).lstrip() if current else line
                if len(candidate) > max_chars:
                    chunks.append(current.rstrip())
                    current = line
                else:
                    current = candidate
        else:
            candidate = (current + "\n\n" + para).lstrip() if current else para
            if len(candidate) > max_chars:
                chunks.append(current.rstrip())
                current = para
            else:
                current = candidate

    if current:
        chunks.append(current.rstrip())

    # Remove empty chunks
    chunks = [c for c in chunks if c]

    if len(chunks) <= 1:
        return chunks or [text[:max_chars]]

    # Label multi-part messages
    n = len(chunks)
    return [f"{c}\n\n({i+1}/{n})" for i, c in enumerate(chunks)]


def _claude_state(data: bytes) -> str:
    """
    Detect Claude Code's current UI state from a raw PTY chunk.
    Returns 'working' | 'idle' | 'unknown'.

    - 'working': footer shows "esc to interrupt" — Claude is thinking/executing
    - 'idle':    footer shows "? for shortcuts" / "plan mode on" / "accept edits on"
                 — Claude finished, waiting for next input
    - 'unknown': no state marker found in this chunk
    """
    text = _ANSI_CLEAN_RE.sub('', data.decode('utf-8', errors='replace'))
    text = text.replace('\r', '').replace(' ', '')
    if _WORKING_RE.search(text):
        return 'working'
    if _IDLE_RE.search(text):
        return 'idle'
    return 'unknown'


# ── Session registry helpers (imported from routes/sessions at runtime) ──

def get_session(name: str) -> Optional[ClaudeSession]:
    from druidclaw.web.state import _sessions, _sessions_lock
    with _sessions_lock:
        return _sessions.get(name)


def create_session(name: str, workdir: str = ".", claude_args: list = None) -> ClaudeSession:
    from druidclaw.web.state import _sessions, _sessions_lock
    # Check under lock — prune dead session with same name first
    with _sessions_lock:
        existing = _sessions.get(name)
        if existing is not None:
            if existing.is_alive():
                raise ValueError(f"会话 '{name}' 已存在")
            # Dead session occupying the name — remove it
            del _sessions[name]
    # Auto-create workdir if it doesn't exist
    workdir_path = Path(workdir).expanduser().resolve()
    if not workdir_path.exists():
        workdir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created workdir: {workdir_path}")
    s = ClaudeSession(name=name, workdir=str(workdir_path), claude_args=claude_args or [])
    s.start()
    # Final insert — check once more in case of race
    with _sessions_lock:
        if name in _sessions and _sessions[name].is_alive():
            s.stop()
            raise ValueError(f"会话 '{name}' 已存在（并发冲突）")
        _sessions[name] = s
    return s


def remove_session(name: str, force: bool = False):
    from druidclaw.web.state import _sessions, _sessions_lock
    with _sessions_lock:
        s = _sessions.pop(name, None)
    if s:
        s.kill() if force else s.stop()


# ── _UserSessionPool ──────────────────────────────────────────────

class _UserSessionPool:
    """
    Manages per-user Claude sessions for a single IM bot card.

    Each (bot_card, user_key) pair gets its own isolated ClaudeSession.
    Sessions are automatically destroyed after `idle_timeout` seconds of
    inactivity, freeing resources for inactive users.

    Session naming: ``{base_name}_u{hash6}``
      e.g. base_name="fbs_abc123", user_key="ou_xxx" → "fbs_abc123_u_d4e5f6"
    """

    MAX_QUEUE = 10   # max pending messages per user before dropping

    def __init__(self, base_name: str, workdir: str = ".",
                 idle_timeout: float = 1800.0, auto_approve: bool = False):
        self._base_name = base_name
        self._workdir = workdir
        self._idle_timeout = idle_timeout
        self._claude_args = ["--dangerously-skip-permissions"] if auto_approve else []
        # Session registry
        self._sessions: dict[str, ClaudeSession] = {}  # user_key → session
        self._timers:   dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        # Per-user message queue (serialises messages so Claude never sees
        # a second message while still processing the first)
        self._queues:     dict[str, _collections.deque] = {}
        self._processing: set = set()          # user_keys currently dispatched
        self._queue_lock  = threading.Lock()   # guards _queues + _processing

    # ── public API ─────────────────────────────────────────────────

    def get_or_create(self, user_key: str) -> ClaudeSession:
        """Return the session for this user, creating one if needed."""
        with self._lock:
            s = self._sessions.get(user_key)
            if s and s.is_alive():
                self._reset_timer_locked(user_key)
                return s
            # Create a fresh session
            name = self._session_name(user_key)
            try:
                s = create_session(name=name, workdir=self._workdir,
                                   claude_args=self._claude_args)
            except ValueError:
                remove_session(name, force=True)
                s = create_session(name=name, workdir=self._workdir,
                                   claude_args=self._claude_args)
            self._sessions[user_key] = s
            self._reset_timer_locked(user_key)
            logger.info(f"[pool:{self._base_name}] Created session '{name}' for user '{user_key[:16]}'")
            return s

    def destroy_all(self):
        """Kill all sessions and clear queues (called when the bot stops)."""
        with self._queue_lock:
            self._queues.clear()
            self._processing.clear()
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
            sessions = dict(self._sessions)
            self._sessions.clear()
        for s in sessions.values():
            logger.info(f"[pool:{self._base_name}] Destroying session '{s.name}'")
            remove_session(s.name, force=True)

    def enqueue(self, user_key: str, text: str,
                chat_id: str, bot, delay: float):
        """
        Add a message to this user's send queue.
        If the user is idle, dispatch immediately; otherwise it will be
        processed automatically after the current message finishes.
        Drops the message if the queue is full (MAX_QUEUE).
        """
        with self._queue_lock:
            if user_key not in self._queues:
                self._queues[user_key] = _collections.deque()
            q = self._queues[user_key]
            if len(q) >= self.MAX_QUEUE:
                logger.warning(
                    f"[pool:{self._base_name}] Queue full for '{user_key[:16]}', dropping message"
                )
                if chat_id and bot:
                    bot.send_message(chat_id,
                        f"⚠️ 队列已满（最多 {self.MAX_QUEUE} 条），请等待当前任务完成后重试。")
                return
            q.append((text, chat_id, bot, delay))
            if user_key in self._processing:
                return   # on_done chain will pick it up
            self._processing.add(user_key)   # claim dispatch slot atomically
        self._do_dispatch(user_key)

    def reset_user(self, user_key: str):
        """Destroy the user's session and clear their queue (for /reset command)."""
        with self._queue_lock:
            self._queues.pop(user_key, None)
            self._processing.discard(user_key)
        with self._lock:
            s = self._sessions.pop(user_key, None)
            t = self._timers.pop(user_key, None)
            if t:
                t.cancel()
        if s:
            logger.info(f"[pool:{self._base_name}] Reset session '{s.name}' for user '{user_key[:16]}'")
            remove_session(s.name, force=True)

    def _do_dispatch(self, user_key: str):
        """
        Pop the next message from the queue and send it to Claude.
        Called after the previous _ReplyCollector flushes (via on_done).
        """
        with self._queue_lock:
            q = self._queues.get(user_key)
            if not q:
                self._processing.discard(user_key)
                return
            text, chat_id, bot, delay = q.popleft()

        s = self.get_or_create(user_key)
        if not s.is_alive():
            logger.warning(
                f"[pool:{self._base_name}] Session for '{user_key[:16]}' is dead, skipping"
            )
            if chat_id and bot:
                bot.send_message(chat_id, "❌ Claude 会话异常，请重试。")
            self._do_dispatch(user_key)   # try next in queue
            return

        logger.info(f"[pool:{self._base_name}] → [{s.name}]: {text[:60]!r}")
        s.send_input((text + "\n").encode("utf-8"))
        _ReplyCollector(s, chat_id, bot, delay, input_text=text,
                        on_done=lambda: self._do_dispatch(user_key))

    # ── internals ──────────────────────────────────────────────────

    def _session_name(self, user_key: str) -> str:
        h = hashlib.md5(user_key.encode()).hexdigest()[:6]
        return f"{self._base_name}_u{h}"

    def _reset_timer_locked(self, user_key: str):
        """Cancel existing idle timer and start a new one. Must hold self._lock."""
        t = self._timers.pop(user_key, None)
        if t:
            t.cancel()
        t = threading.Timer(self._idle_timeout, self._expire, args=(user_key,))
        t.daemon = True
        t.start()
        self._timers[user_key] = t

    def _expire(self, user_key: str):
        with self._lock:
            s = self._sessions.pop(user_key, None)
            self._timers.pop(user_key, None)
        if s:
            logger.info(
                f"[pool:{self._base_name}] Session '{s.name}' expired "
                f"(idle > {self._idle_timeout}s)"
            )
            remove_session(s.name, force=True)


# ── _ReplyCollector ───────────────────────────────────────────────

class _ReplyCollector:
    """
    Attaches to a ClaudeSession as an output callback, buffers PTY output,
    and sends it back to the IM chat when Claude finishes.

    Detection strategy (priority order):
    1. Claude Code idle marker detected in PTY stream
       (? for shortcuts / plan mode on / accept edits on)
       → flush after CONFIRM_DELAY (0.3 s) — fast & accurate
    2. N-second silence fallback — for chunks without state markers
    3. Absolute 300 s deadline — covers long-running tasks / hung sessions
    """
    WARMUP        = 0.8     # skip input echo + initial TUI redraw
    CONFIRM_DELAY = 0.3     # confirmation wait after idle marker detected
    MAX_WAIT      = 300.0   # absolute deadline for long-running tasks

    def __init__(self, session: "ClaudeSession", chat_id: str,
                 bot, delay: float, input_text: str = "",
                 on_done: Optional[callable] = None):
        self._session = session
        self._chat_id = chat_id
        self._bot = bot
        self._delay = delay
        self._input_text = input_text
        self._on_done = on_done   # called after flush (drives message queue)
        self._buf = bytearray()
        self._buf_lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._max_timer: Optional[threading.Timer] = None
        self._done = False

        # Delay registration to skip echo + initial UI redraw
        warmup = threading.Timer(self.WARMUP, self._start_collecting)
        warmup.daemon = True
        warmup.start()
        self._start_time = time.time()
        # Absolute deadline — covers long-running tasks (default 300 s)
        self._max_timer = threading.Timer(self.WARMUP + self.MAX_WAIT, self._flush)
        self._max_timer.daemon = True
        self._max_timer.start()

    def _start_collecting(self):
        if self._done:
            return
        self._session.add_output_callback(self._on_output)
        # Start silence timer immediately (Claude may already have responded)
        with self._buf_lock:
            if not self._done and not self._timer:
                self._timer = threading.Timer(self._delay, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _on_output(self, data: bytes):
        with self._buf_lock:
            if self._done:
                return
            self._buf.extend(data)

            state = _claude_state(data)
            if state == 'working':
                # Claude still busy — cancel any pending flush so we don't
                # send a partial response mid-execution
                if self._timer:
                    self._timer.cancel()
                    self._timer = None
            elif state == 'idle':
                # Claude just finished — short confirmation delay then flush
                if self._timer:
                    self._timer.cancel()
                self._timer = threading.Timer(self.CONFIRM_DELAY, self._flush)
                self._timer.daemon = True
                self._timer.start()
            else:
                # No state marker — fall back to silence timer
                if self._timer:
                    self._timer.cancel()
                self._timer = threading.Timer(self._delay, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self):
        with self._buf_lock:
            if self._done:
                return
            self._done = True
            buf = bytes(self._buf)
            if self._timer:
                self._timer.cancel()
            if self._max_timer:
                self._max_timer.cancel()

        self._session.remove_output_callback(self._on_output)
        try:
            if not buf:
                return

            raw = buf.decode("utf-8", errors="replace")
            text = _clean_output(raw, skip_echo=self._input_text)
            if not text:
                return

            elapsed = time.time() - self._start_time
            if elapsed >= 60:
                elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
            else:
                elapsed_str = f"{elapsed:.0f}s"

            chunks = _split_message(text)
            # Append timing footer to last chunk
            footer = f"\n─────────────────────\n⏱ 耗时 {elapsed_str}"
            chunks[-1] = chunks[-1] + footer

            all_ok = True
            for chunk in chunks:
                if not self._bot.send_message(self._chat_id, chunk):
                    logger.warning(f"Failed to send reply chunk to {self._chat_id}")
                    all_ok = False
                    break
            if all_ok:
                self._bot._add_reply_event(text, self._chat_id)
        finally:
            # Always advance the message queue regardless of send success
            if self._on_done:
                self._on_done()


# ── IM command handler ────────────────────────────────────────────

def _handle_im_cmd(bot, text: str, chat_id: str, session_name: str,
                   pool: "Optional[_UserSessionPool]" = None,
                   user_key: str = "") -> bool:
    """
    Handle built-in IM bot commands. Returns True if handled.

    General commands:
      /help              — show all commands
      /reset             — destroy session and start fresh
      /status            — show current session info

    Scheduled task commands:
      /task [help]
      /task list
      /task add <30m|1h|cron EXPR> <prompt…>
      /task del  <id>
      /task run  <id>
      /task on / off <id>
    """
    cmd = text.strip()

    def reply(msg: str):
        if chat_id:
            bot.send_message(chat_id, msg)

    # ── /help ──────────────────────────────────────────────
    if cmd == '/help':
        reply(
            '📖 可用命令:\n'
            '/help              — 显示本帮助\n'
            '/reset             — 清除上下文，开始新对话\n'
            '/status            — 查看当前会话状态\n'
            '/task list         — 查看定时任务\n'
            '/task add 30m <提词> — 新建定时任务\n'
            '/task del <id>     — 删除任务\n'
            '/task run <id>     — 立即触发任务\n'
            '/task on/off <id>  — 启用/禁用任务\n'
            '\n其他消息直接发给 Claude 处理。'
        )
        return True

    # ── /reset ─────────────────────────────────────────────
    if cmd == '/reset':
        if pool and user_key:
            pool.reset_user(user_key)
        reply('✅ 会话已重置，下次消息将开始全新对话。')
        return True

    # ── /status ────────────────────────────────────────────
    if cmd == '/status':
        s = get_session(session_name) if session_name else None
        if s and s.is_alive():
            elapsed = int(time.time() - s._start_time) if hasattr(s, '_start_time') else 0
            uptime = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"
            reply(f'✅ 会话运行中\n名称: {s.name}\n运行时长: {uptime}\nPID: {s.pid}')
        else:
            reply('⚪ 当前没有活跃会话，发消息即可自动创建。')
        return True

    if not (cmd == '/task' or cmd.startswith('/task ')):
        return False

    parts = text.strip().split(None, 2)   # ['/task', subcmd, rest]
    subcmd = parts[1].lower() if len(parts) > 1 else 'help'

    # ── list ────────────────────────────────────────────────
    if subcmd == 'list':
        with _sched_lock:
            my = [t for t in _sched_tasks if t.get('session_name') == session_name]
        if not my:
            reply('📋 当前没有定时任务。\n用 /task add 30m <提词> 新建一个。')
        else:
            lines = ['📋 定时任务列表:']
            for t in my:
                sched = f"Cron:{t['cron_expr']}" if t['schedule_type'] == 'cron' \
                        else f"每{t['interval_minutes']}分钟"
                state = '✅' if t['enabled'] else '⏸'
                lines.append(f"{state} [{t['id']}] {t['name']} · {sched}\n   → {t['prompt'][:60]}")
            reply('\n'.join(lines))
        return True

    # ── add ─────────────────────────────────────────────────
    if subcmd == 'add':
        # /task add <schedule> <prompt>
        # schedule: 30m | 2h | cron <expr(5 fields)>
        rest = parts[2].strip() if len(parts) > 2 else ''
        if not rest:
            reply('用法: /task add <30m|2h|cron 0 9 * * 1-5> <提词内容>')
            return True

        stype = 'interval'
        interval = 60
        cron_expr = '0 * * * *'
        prompt = ''

        if rest.lower().startswith('cron '):
            # cron 5-field + prompt: "cron 0 9 * * 1-5 提词"
            after_cron = rest[5:].strip()
            cron_parts = after_cron.split(None, 5)
            if len(cron_parts) < 6:
                reply('❌ Cron 格式: /task add cron <分 时 日 月 周> <提词>\n示例: /task add cron 0 9 * * 1-5 每日早报')
                return True
            cron_expr = ' '.join(cron_parts[:5])
            prompt    = cron_parts[5].strip()
            stype     = 'cron'
        else:
            # interval: "30m 提词" or "2h 提词"
            tokens = rest.split(None, 1)
            sched_tok = tokens[0].lower()
            prompt    = tokens[1].strip() if len(tokens) > 1 else ''
            try:
                if sched_tok.endswith('h'):
                    interval = int(sched_tok[:-1]) * 60
                elif sched_tok.endswith('m'):
                    interval = int(sched_tok[:-1])
                else:
                    interval = int(sched_tok)
            except ValueError:
                reply('❌ 间隔格式示例: 30m / 2h / 60\n用法: /task add 30m <提词>')
                return True

        if not prompt:
            reply('❌ 提词内容不能为空')
            return True

        import uuid as _u
        task = {
            'id':               _u.uuid4().hex[:8],
            'name':             f'{session_name}-task',
            'session_name':     session_name,
            'prompt':           prompt,
            'schedule_type':    stype,
            'interval_minutes': max(1, interval),
            'cron_expr':        cron_expr,
            'enabled':          True,
            'last_run':         None,
            'run_count':        0,
            'created_at':       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        with _sched_lock:
            _sched_tasks.append(task)
        _save_sched_tasks()
        sched_label = f"Cron: {cron_expr}" if stype == 'cron' \
                      else f"每 {interval} 分钟"
        reply(f'✅ 任务已创建 [{task["id"]}]\n📅 {sched_label}\n→ {prompt[:80]}')
        return True

    # ── del ─────────────────────────────────────────────────
    if subcmd == 'del':
        tid = parts[2].strip() if len(parts) > 2 else ''
        with _sched_lock:
            idx = next((i for i, t in enumerate(_sched_tasks)
                        if t['id'] == tid and t.get('session_name') == session_name), None)
            if idx is None:
                reply(f'❌ 未找到任务 [{tid}]，用 /task list 查看')
                return True
            _sched_tasks.pop(idx)
        _save_sched_tasks()
        reply(f'🗑 任务 [{tid}] 已删除')
        return True

    # ── run ─────────────────────────────────────────────────
    if subcmd == 'run':
        tid = parts[2].strip() if len(parts) > 2 else ''
        with _sched_lock:
            task = next((t for t in _sched_tasks
                         if t['id'] == tid and t.get('session_name') == session_name), None)
        if task is None:
            reply(f'❌ 未找到任务 [{tid}]，用 /task list 查看')
            return True
        threading.Thread(target=_fire_sched_task, args=(task,), daemon=True).start()
        reply(f'▶ 任务 [{tid}] 已触发')
        return True

    # ── on / off ────────────────────────────────────────────
    if subcmd in ('on', 'off'):
        tid    = parts[2].strip() if len(parts) > 2 else ''
        enable = subcmd == 'on'
        with _sched_lock:
            task = next((t for t in _sched_tasks
                         if t['id'] == tid and t.get('session_name') == session_name), None)
            if task is None:
                reply(f'❌ 未找到任务 [{tid}]')
                return True
            task['enabled'] = enable
        _save_sched_tasks()
        reply(f'{"✅ 已启用" if enable else "⏸ 已禁用"} 任务 [{tid}]')
        return True

    # ── help (default) ──────────────────────────────────────
    reply(
        '⏰ 定时任务命令:\n'
        '/task list              — 查看任务列表\n'
        '/task add 30m <提词>    — 每30分钟触发\n'
        '/task add 2h <提词>     — 每2小时触发\n'
        '/task add cron 0 9 * * 1-5 <提词>  — Cron表达式\n'
        '/task del <id>          — 删除任务\n'
        '/task run <id>          — 立即触发一次\n'
        '/task on/off <id>       — 启用/禁用任务'
    )
    return True


def _save_sched_tasks():
    from druidclaw.web.state import TASKS_FILE, _sched_tasks, _sched_lock
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with _sched_lock:
        TASKS_FILE.write_text(json.dumps(_sched_tasks, indent=2, ensure_ascii=False))


def _fire_sched_task(task: dict):
    """Send the task prompt to the target Claude session."""
    sess_name = task.get("session_name", "")
    prompt    = task.get("prompt", "").strip()
    if not prompt:
        return
    s = get_session(sess_name)
    if not s or not s.is_alive():
        logger.warning(f"[SchedTask {task['id']}] session '{sess_name}' not alive, skip")
        return
    s.send_input((prompt + "\n").encode("utf-8"))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[SchedTask {task['id']}] → '{sess_name}': {prompt[:60]!r}")
    with _sched_lock:
        for t in _sched_tasks:
            if t["id"] == task["id"]:
                t["last_run"]  = now_str
                t["run_count"] = t.get("run_count", 0) + 1
                break
    _save_sched_tasks()


# ── Image download helpers ─────────────────────────────────────────

def _fetch_url_bytes(url: str, headers: dict = None,
                     timeout: int = 15) -> Optional[bytes]:
    """Download raw bytes from a URL, return None on any failure."""
    try:
        import httpx
        r = httpx.get(url, headers=headers or {}, timeout=timeout,
                      follow_redirects=True)
        if r.status_code == 200 and r.content:
            return r.content
        logger.warning(f"Image download HTTP {r.status_code}: {url[:60]}")
    except Exception as e:
        logger.warning(f"Image download error [{url[:60]}]: {e}")
    return None


def _feishu_tenant_token(app_id: str, app_secret: str) -> Optional[str]:
    """Get a Feishu tenant_access_token (short-lived, ~2h)."""
    try:
        import httpx
        r = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=5,
        )
        d = r.json()
        if d.get("code") == 0:
            return d["tenant_access_token"]
        logger.warning(f"Feishu token error code={d.get('code')}: {d.get('msg')}")
    except Exception as e:
        logger.warning(f"Feishu token request failed: {e}")
    return None


def _save_temp_image(data: bytes, ext: str = "jpg") -> str:
    """Save image bytes to a temp file, return its path."""
    f = _tempfile.NamedTemporaryFile(
        suffix=f".{ext}", prefix="cc_img_", delete=False
    )
    f.write(data)
    f.close()
    return f.name


def _image_prompt(file_path: str, caption: str = "") -> str:
    """
    Build the text prompt Claude Code will receive for an image.
    Claude Code's Read tool can open image files and the model 'sees' them.
    """
    if caption:
        return f"{caption}\n\n[图片已保存至 {file_path}，请用 Read 工具查看后回答]"
    return f"[图片已保存至 {file_path}，请用 Read 工具查看并描述或处理其中内容]"


# ── IM event handlers ─────────────────────────────────────────────

def _on_feishu_event(bot: FeishuBot, event: dict):
    """
    Per-bot Feishu event handler.
    Routes im.message.receive_v1 events to the sender's own Claude session.
    Each sender (open_id) gets an isolated session via _UserSessionPool.
    """
    header = event.get("header", {})
    if header.get("event_type") != "im.message.receive_v1":
        return

    pool: Optional[_UserSessionPool] = getattr(bot, '_user_pool', None)
    if not pool:
        return

    delay = float(getattr(bot, '_reply_delay', _bridge_cfg.get("reply_delay", 2.0)))

    evt_body = event.get("event", {})
    msg = evt_body.get("message", {})
    chat_id = msg.get("chat_id", "")
    sender  = evt_body.get("sender", {})
    user_key = sender.get("sender_id", {}).get("open_id", "") or chat_id
    if not user_key:
        return

    msg_type = msg.get("message_type", "")
    try:
        content_raw = json.loads(msg.get("content", "{}"))
    except Exception:
        return

    if msg_type == "text":
        text = content_raw.get("text", "").strip()
        if not text:
            return
    elif msg_type == "image":
        image_key = content_raw.get("image_key", "")
        if not image_key:
            return
        token = _feishu_tenant_token(bot.app_id, bot.app_secret)
        if not token:
            if chat_id:
                bot.send_message(chat_id, "❌ 图片下载失败（无法获取授权），请重试。")
            return
        img_data = _fetch_url_bytes(
            f"https://open.feishu.cn/open-apis/im/v1/images/{image_key}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if not img_data:
            if chat_id:
                bot.send_message(chat_id, "❌ 图片下载失败，请重试。")
            return
        text = _image_prompt(_save_temp_image(img_data))
    else:
        if chat_id:
            bot.send_message(chat_id, f"⚠️ 暂不支持「{msg_type}」类型消息，请发送文字或图片。")
        return

    if _handle_im_cmd(bot, text, chat_id, pool._session_name(user_key),
                      pool=pool, user_key=user_key):
        return

    pool.enqueue(user_key, text, chat_id, bot, delay)


def _on_telegram_event(bot: TelegramBot, update: dict):
    """Route Telegram messages to the sender's own Claude session."""
    msg = (update.get("message")
           or update.get("channel_post")
           or update.get("edited_message"))
    if not msg:
        return

    pool: Optional[_UserSessionPool] = getattr(bot, '_user_pool', None)
    if not pool:
        return

    delay = float(getattr(bot, '_reply_delay', _bridge_cfg.get("reply_delay", 2.0)))

    chat_id  = str(msg.get("chat", {}).get("id", ""))
    user_key = str(msg.get("from", {}).get("id", "")) or chat_id
    if not user_key:
        return

    if "text" in msg:
        text = msg["text"].strip()
        if not text:
            return
    elif "photo" in msg:
        # photo is a list of PhotoSize; last entry is largest
        file_id = msg["photo"][-1]["file_id"]
        try:
            import httpx
            r = httpx.get(f"{bot._api}/getFile", params={"file_id": file_id}, timeout=5)
            file_path_tg = r.json().get("result", {}).get("file_path", "")
        except Exception as e:
            logger.warning(f"Telegram getFile error: {e}")
            file_path_tg = ""
        if not file_path_tg:
            if chat_id:
                bot.send_message(chat_id, "❌ 图片下载失败，请重试。")
            return
        api_base = bot._api.replace(f"/bot{bot.token}", "")
        img_data = _fetch_url_bytes(
            f"{api_base}/file/bot{bot.token}/{file_path_tg}"
        )
        if not img_data:
            if chat_id:
                bot.send_message(chat_id, "❌ 图片下载失败，请重试。")
            return
        caption = msg.get("caption", "").strip()
        text = _image_prompt(_save_temp_image(img_data), caption)
    else:
        if chat_id:
            bot.send_message(chat_id, "⚠️ 暂不支持该消息类型，请发送文字或图片。")
        return

    if _handle_im_cmd(bot, text, chat_id, pool._session_name(user_key),
                      pool=pool, user_key=user_key):
        return

    pool.enqueue(user_key, text, chat_id, bot, delay)


def _on_dingtalk_event(bot: DingtalkBot, data: dict):
    """Route DingTalk messages to the sender's own Claude session."""
    pool: Optional[_UserSessionPool] = getattr(bot, '_user_pool', None)
    if not pool:
        return

    delay = float(getattr(bot, '_reply_delay', _bridge_cfg.get("reply_delay", 2.0)))

    chat_id  = data.get("sessionWebhook") or data.get("conversationId", "")
    if not chat_id:
        return
    user_key = data.get("senderStaffId") or data.get("senderId") or chat_id

    msg_type = data.get("msgtype", "text")
    if msg_type == "text":
        try:
            text = data.get("text", {}).get("content", "").strip()
        except Exception:
            return
        if not text:
            return
    elif msg_type == "picture":
        pic_url = (data.get("content", {}).get("picURL")
                   or data.get("content", {}).get("downloadCode", ""))
        if not pic_url:
            return
        img_data = _fetch_url_bytes(pic_url)
        if not img_data:
            bot.send_message(chat_id, "❌ 图片下载失败，请重试。")
            return
        text = _image_prompt(_save_temp_image(img_data))
    else:
        bot.send_message(chat_id, f"⚠️ 暂不支持「{msg_type}」类型消息，请发送文字或图片。")
        return

    if _handle_im_cmd(bot, text, chat_id, pool._session_name(user_key),
                      pool=pool, user_key=user_key):
        return

    pool.enqueue(user_key, text, chat_id, bot, delay)


def _on_qq_event(bot: QQBot, event: dict):
    """Route QQ OneBot v11 messages to the sender's own Claude session."""
    if event.get("post_type") != "message":
        return

    pool: Optional[_UserSessionPool] = getattr(bot, '_user_pool', None)
    if not pool:
        return

    delay = float(getattr(bot, '_reply_delay', _bridge_cfg.get("reply_delay", 2.0)))

    user_key = str(event.get("user_id", ""))
    if not user_key:
        return
    msg_type = event.get("message_type", "")
    if msg_type == "group":
        chat_id = f"group:{event.get('group_id', '')}"
    else:
        chat_id = f"private:{event.get('user_id', '')}"

    segments = event.get("message", [])
    if not isinstance(segments, list):
        # CQ-code string — extract text only
        raw = event.get("raw_message", "") or str(segments)
        text = raw.strip()
        if not text:
            return
    else:
        # Structured segments: collect text and handle first image
        text_parts = []
        img_url    = ""
        for seg in segments:
            if seg.get("type") == "text":
                text_parts.append(seg.get("data", {}).get("text", ""))
            elif seg.get("type") == "image" and not img_url:
                img_url = seg.get("data", {}).get("url", "")

        if img_url:
            img_data = _fetch_url_bytes(img_url)
            if img_data:
                caption = "".join(text_parts).strip()
                text = _image_prompt(_save_temp_image(img_data), caption)
            else:
                bot.send_message(chat_id, "❌ 图片下载失败，请重试。")
                return
        else:
            text = "".join(text_parts).strip()
            if not text:
                return

    if _handle_im_cmd(bot, text, chat_id, pool._session_name(user_key),
                      pool=pool, user_key=user_key):
        return

    pool.enqueue(user_key, text, chat_id, bot, delay)


def _on_wework_event(bot: WeWorkBot, data: dict):
    """Route WeWork messages to the sender's own Claude session."""
    msg_type = data.get("type", "")
    if msg_type not in ("text", "image"):
        return

    pool: Optional[_UserSessionPool] = getattr(bot, '_user_pool', None)
    if not pool:
        return

    delay = float(getattr(bot, '_reply_delay', _bridge_cfg.get("reply_delay", 2.0)))

    user_key = data.get("from_user", "")
    if not user_key:
        return
    chat_id = user_key

    if msg_type == "text":
        text = data.get("content", "").strip()
        if not text:
            return
    else:  # image
        pic_url = data.get("pic_url", "")
        if not pic_url:
            bot.send_message(chat_id, "❌ 图片地址缺失，无法下载。")
            return
        img_data = _fetch_url_bytes(pic_url)
        if not img_data:
            bot.send_message(chat_id, "❌ 图片下载失败，请重试。")
            return
        text = _image_prompt(_save_temp_image(img_data))

    if _handle_im_cmd(bot, text, chat_id, pool._session_name(user_key),
                      pool=pool, user_key=user_key):
        return

    pool.enqueue(user_key, text, chat_id, bot, delay)


# ── Bot start/stop/get helpers ────────────────────────────────────

def _start_feishu_bot(app_id: str, app_secret: str,
                      auto_session_name: str = "",
                      card_id: str = "__legacy__",
                      auto_approve: bool = False,
                      workdir: str = ".") -> FeishuBot:
    """Start a Feishu bot keyed by card_id."""
    global _feishu_bots
    with _feishu_lock:
        # Stop previous bot for this card (same card restarted)
        old = _feishu_bots.pop(card_id, None)
        if old:
            old.stop()

        bot = FeishuBot(app_id=app_id, app_secret=app_secret)
        bot._auto_session_name = auto_session_name
        bot._card_id = card_id

        # Per-bot event handler (closure captures this bot instance)
        def _make_handler(b: FeishuBot):
            def handler(event: dict):
                _on_feishu_event(b, event)
            return handler
        bot.add_handler(_make_handler(bot))

        if auto_session_name:
            sess_name = auto_session_name

            def _on_bot_connect(b: FeishuBot):
                logger.info(f"[{card_id}] Feishu connected → creating user session pool (base='{sess_name}', workdir='{workdir}', auto_approve={auto_approve})")
                b._user_pool = _UserSessionPool(base_name=sess_name, workdir=workdir, auto_approve=auto_approve)
                b._add_system_event("info", f"已就绪（多用户模式），基础名: {sess_name}")

            def _on_bot_disconnect(b: FeishuBot):
                logger.info(f"[{card_id}] Feishu disconnected → destroying all user sessions")
                pool = getattr(b, '_user_pool', None)
                if pool:
                    pool.destroy_all()
                    b._user_pool = None
                b._add_system_event("info", f"已关闭所有用户会话 (base='{sess_name}')")

            bot.add_connect_callback(_on_bot_connect)
            bot.add_disconnect_callback(_on_bot_disconnect)

        bot.start()
        _feishu_bots[card_id] = bot
    return bot


def _stop_feishu_bot(card_id: Optional[str] = None):
    """Stop a single bot (by card_id) or all bots if card_id is None."""
    global _feishu_bots
    with _feishu_lock:
        if card_id is not None:
            bot = _feishu_bots.pop(card_id, None)
            if bot:
                bot.stop()
        else:
            for bot in list(_feishu_bots.values()):
                bot.stop()
            _feishu_bots.clear()


def _get_feishu_bot(card_id: str = "__legacy__") -> Optional[FeishuBot]:
    with _feishu_lock:
        return _feishu_bots.get(card_id)


def _start_telegram_bot(token: str, auto_session_name: str = "",
                        card_id: str = "",
                        auto_approve: bool = False,
                        workdir: str = ".") -> TelegramBot:
    global _telegram_bots
    with _telegram_lock:
        old = _telegram_bots.pop(card_id, None)
        if old:
            old.stop()
        bot = TelegramBot(token=token)
        bot._auto_session_name = auto_session_name
        bot._card_id = card_id

        def _make_handler(b: TelegramBot):
            def handler(update: dict):
                _on_telegram_event(b, update)
            return handler
        bot.add_handler(_make_handler(bot))

        if auto_session_name:
            sess_name = auto_session_name

            def _on_connect(b: TelegramBot):
                logger.info(f"[{card_id}] Telegram connected → creating user session pool (base='{sess_name}', workdir='{workdir}', auto_approve={auto_approve})")
                b._user_pool = _UserSessionPool(base_name=sess_name, workdir=workdir, auto_approve=auto_approve)
                b._add_system_event("info", f"已就绪（多用户模式），基础名: {sess_name}")

            def _on_disconnect(b: TelegramBot):
                logger.info(f"[{card_id}] Telegram disconnected → destroying all user sessions")
                pool = getattr(b, '_user_pool', None)
                if pool:
                    pool.destroy_all()
                    b._user_pool = None

            bot.add_connect_callback(_on_connect)
            bot.add_disconnect_callback(_on_disconnect)

        bot.start()
        _telegram_bots[card_id] = bot
    return bot


def _stop_telegram_bot(card_id: Optional[str] = None):
    global _telegram_bots
    with _telegram_lock:
        if card_id is not None:
            bot = _telegram_bots.pop(card_id, None)
            if bot:
                bot.stop()
        else:
            for bot in list(_telegram_bots.values()):
                bot.stop()
            _telegram_bots.clear()


def _get_telegram_bot(card_id: str) -> Optional[TelegramBot]:
    with _telegram_lock:
        return _telegram_bots.get(card_id)


def _start_dingtalk_bot(app_key: str, app_secret: str,
                        auto_session_name: str = "",
                        card_id: str = "",
                        auto_approve: bool = False,
                        workdir: str = ".") -> DingtalkBot:
    global _dingtalk_bots
    with _dingtalk_lock:
        old = _dingtalk_bots.pop(card_id, None)
        if old:
            old.stop()
        bot = DingtalkBot(app_key=app_key, app_secret=app_secret)
        bot._auto_session_name = auto_session_name
        bot._card_id = card_id

        def _make_handler(b: DingtalkBot):
            def handler(data: dict):
                _on_dingtalk_event(b, data)
            return handler
        bot.add_handler(_make_handler(bot))

        if auto_session_name:
            sess_name = auto_session_name

            def _on_connect(b: DingtalkBot):
                logger.info(f"[{card_id}] DingTalk connected → creating user session pool (base='{sess_name}', workdir='{workdir}', auto_approve={auto_approve})")
                b._user_pool = _UserSessionPool(base_name=sess_name, workdir=workdir, auto_approve=auto_approve)
                b._add_system_event("info", f"已就绪（多用户模式），基础名: {sess_name}")

            def _on_disconnect(b: DingtalkBot):
                logger.info(f"[{card_id}] DingTalk disconnected → destroying all user sessions")
                pool = getattr(b, '_user_pool', None)
                if pool:
                    pool.destroy_all()
                    b._user_pool = None

            bot.add_connect_callback(_on_connect)
            bot.add_disconnect_callback(_on_disconnect)

        bot.start()
        _dingtalk_bots[card_id] = bot
    return bot


def _stop_dingtalk_bot(card_id: Optional[str] = None):
    global _dingtalk_bots
    with _dingtalk_lock:
        if card_id is not None:
            bot = _dingtalk_bots.pop(card_id, None)
            if bot:
                bot.stop()
        else:
            for bot in list(_dingtalk_bots.values()):
                bot.stop()
            _dingtalk_bots.clear()


def _get_dingtalk_bot(card_id: str) -> Optional[DingtalkBot]:
    with _dingtalk_lock:
        return _dingtalk_bots.get(card_id)


def _start_qq_bot(ws_url: str, access_token: str = "",
                  auto_session_name: str = "",
                  card_id: str = "",
                  auto_approve: bool = False,
                  workdir: str = ".") -> QQBot:
    global _qq_bots
    with _qq_lock:
        old = _qq_bots.pop(card_id, None)
        if old:
            old.stop()
        bot = QQBot(ws_url=ws_url, access_token=access_token)
        bot._auto_session_name = auto_session_name
        bot._card_id = card_id

        def _make_handler(b: QQBot):
            def handler(event: dict):
                _on_qq_event(b, event)
            return handler
        bot.add_handler(_make_handler(bot))

        if auto_session_name:
            sess_name = auto_session_name

            def _on_connect(b: QQBot):
                logger.info(f"[{card_id}] QQ connected → creating user session pool (base='{sess_name}', workdir='{workdir}', auto_approve={auto_approve})")
                b._user_pool = _UserSessionPool(base_name=sess_name, workdir=workdir, auto_approve=auto_approve)
                b._add_system_event("info", f"已就绪（多用户模式），基础名: {sess_name}")

            def _on_disconnect(b: QQBot):
                logger.info(f"[{card_id}] QQ disconnected → destroying all user sessions")
                pool = getattr(b, '_user_pool', None)
                if pool:
                    pool.destroy_all()
                    b._user_pool = None

            bot.add_connect_callback(_on_connect)
            bot.add_disconnect_callback(_on_disconnect)

        bot.start()
        _qq_bots[card_id] = bot
    return bot


def _stop_qq_bot(card_id: Optional[str] = None):
    global _qq_bots
    with _qq_lock:
        if card_id is not None:
            bot = _qq_bots.pop(card_id, None)
            if bot:
                bot.stop()
        else:
            for bot in list(_qq_bots.values()):
                bot.stop()
            _qq_bots.clear()


def _get_qq_bot(card_id: str) -> Optional[QQBot]:
    with _qq_lock:
        return _qq_bots.get(card_id)


def _start_wework_bot(corp_id: str, agent_id: str, corp_secret: str,
                      token: str, encoding_aes_key: str,
                      auto_session_name: str = "",
                      card_id: str = "",
                      auto_approve: bool = False,
                      workdir: str = ".") -> WeWorkBot:
    global _wework_bots
    with _wework_lock:
        old = _wework_bots.pop(card_id, None)
        if old:
            old.stop()
        bot = WeWorkBot(corp_id=corp_id, agent_id=agent_id,
                        corp_secret=corp_secret, token=token,
                        encoding_aes_key=encoding_aes_key)
        bot._auto_session_name = auto_session_name
        bot._card_id = card_id

        def _make_handler(b: WeWorkBot):
            def handler(data: dict):
                _on_wework_event(b, data)
            return handler
        bot.add_handler(_make_handler(bot))

        if auto_session_name:
            sess_name = auto_session_name

            def _on_connect(b: WeWorkBot):
                logger.info(f"[{card_id}] WeWork connected → creating user session pool (base='{sess_name}', workdir='{workdir}', auto_approve={auto_approve})")
                b._user_pool = _UserSessionPool(base_name=sess_name, workdir=workdir, auto_approve=auto_approve)
                b._add_system_event("info", f"已就绪（多用户模式），基础名: {sess_name}")

            def _on_disconnect(b: WeWorkBot):
                logger.info(f"[{card_id}] WeWork disconnected → destroying all user sessions")
                pool = getattr(b, '_user_pool', None)
                if pool:
                    pool.destroy_all()
                    b._user_pool = None

            bot.add_connect_callback(_on_connect)
            bot.add_disconnect_callback(_on_disconnect)

        bot.start()
        _wework_bots[card_id] = bot
    return bot


def _stop_wework_bot(card_id: Optional[str] = None):
    global _wework_bots
    with _wework_lock:
        if card_id is not None:
            bot = _wework_bots.pop(card_id, None)
            if bot:
                bot.stop()
        else:
            for bot in list(_wework_bots.values()):
                bot.stop()
            _wework_bots.clear()


def _get_wework_bot(card_id: str) -> Optional[WeWorkBot]:
    with _wework_lock:
        return _wework_bots.get(card_id)
