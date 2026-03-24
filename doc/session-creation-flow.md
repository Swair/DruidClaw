# DruidClaw 会话创建流程文档

## 概述

DruidClaw 支持三种类型的终端会话：
1. **Claude 会话** - 运行 Claude Code AI 助手
2. **本地终端** - 本地 Shell 会话
3. **远程终端** - SSH 远程连接

---

## 1. Claude 会话创建流程

### 1.1 调用入口

| 入口 | 文件位置 | 说明 |
|------|----------|------|
| REST API | `web/routes/sessions.py:api_new_session()` | POST `/api/sessions` |
| 卡片创建 | `web/routes/cards.py:api_cards_create()` | POST `/api/cards` |
| WebSocket 自动创建 | `web/routes/sessions.py:ws_attach()` | WS `/ws/{name}` |
| Bridge 函数 | `web/bridge.py:create_session()` | 内部调用 |

### 1.2 创建流程图

```
用户请求 (API/卡片)
    │
    ▼
web/routes/sessions.py:api_new_session(req)
    │ 1. 清理已死亡的会话
    │ 2. 生成会话名 (如 session1, session2...)
    │ 3. 检查工作目录是否存在
    │
    ▼
web/bridge.py:create_session(name, workdir, claude_args)
    │ 1. 检查会话名是否被占用
    │ 2. 自动创建不存在的目录
    │ 3. 创建 ClaudeSession 实例
    │
    ▼
core/session.py:ClaudeSession.__init__()
    │ - 初始化会话名、工作目录、参数
    │ - 创建输出缓冲区 (64KB 环形缓冲)
    │ - 创建 IORecorder 记录日志
    │ - 初始化终端尺寸 (24x80)
    │
    ▼
core/session.py:ClaudeSession.start()
    │
    ├─► Unix 平台 ──► _start_unix(env)
    │   1. 构建命令：`claude [args]`
    │   2. 调用 pty.openpty() 创建 PTY
    │   3. os.fork() 创建子进程
    │   4. 子进程：设置会话领导，绑定 PTY，execvpe 执行 claude
    │   5. 父进程：保存 master_fd 和 child_pid
    │
    └─► Windows 平台 ──► _start_windows(env)
        1. 查找 claude 或 npx 路径 (_find_claude_windows)
        2. 构建命令字符串
        3. 创建 winpty.PTY(rows=24, cols=80)
        4. 调用 pty.spawn() 启动进程
        5. 保存 pid
    │
    ▼
_reader_loop() 后台线程启动
    │ - 持续读取 PTY 输出
    │ - 写入 IORecorder 日志
    │ - 调用输出回调 (WebSocket 推送)
    │
    ▼
注册到全局状态
    │ web/state.py:_sessions[name] = session
    │
    ▼
返回会话信息 {name, pid, workdir, ...}
```

### 1.3 核心代码路径

```python
# 1. API 入口 (sessions.py:50-79)
@router.post("/api/sessions")
def api_new_session(req: NewSessionRequest):
    # 清理死亡会话
    with _sessions_lock:
        dead = [n for n, s in _sessions.items() if not s.is_alive()]
        for n in dead: del _sessions[n]

    # 生成名称
    name = req.name or auto_increment_name()

    # 创建工作目录
    workdir_path = Path(req.workdir).expanduser().resolve()
    if not workdir_path.exists():
        workdir_path.mkdir(parents=True, exist_ok=True)

    # 创建会话
    s = create_session(name=name, workdir=req.workdir, claude_args=req.args)
    return {"name": name, "pid": s.pid, ...}

# 2. Bridge 层 (bridge.py:220-243)
def create_session(name: str, workdir: str = ".", claude_args: list = None):
    with _sessions_lock:
        existing = _sessions.get(name)
        if existing and existing.is_alive():
            raise ValueError(f"会话 '{name}' 已存在")
        if existing: del _sessions[name]  # 清理死亡会话

    # 创建并启动
    s = ClaudeSession(name=name, workdir=str(workdir_path), claude_args=claude_args)
    s.start()

    # 注册
    with _sessions_lock:
        _sessions[name] = s
    return s

# 3. Unix 平台启动 (session.py:191-215)
def _start_unix(self, env: dict):
    cmd = ['claude'] + (self.claude_args or [])
    master_fd, slave_fd = pty.openpty()
    self._set_pty_size(master_fd, *self._term_size)

    child_pid = os.fork()
    if child_pid == 0:  # 子进程
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0); os.dup2(slave_fd, 1); os.dup2(slave_fd, 2)
        os.chdir(self.workdir)
        os.execvpe(cmd[0], cmd, env)
        os._exit(1)

    os.close(slave_fd)
    self.pid = child_pid
    self.master_fd = master_fd
    self._running = True

# 4. Windows 平台启动 (session.py:156-169)
def _start_windows(self, env: dict):
    from winpty import PTY
    cmd_str = self._build_claude_cmd()
    env_str = '\0'.join(f'{k}={v}' for k, v in env.items()) + '\0'

    self._pty = PTY(rows=24, cols=80)
    self._pty.spawn(cmd_str, cmdline=None, cwd=self.workdir, env=env_str)
    self.pid = self._pty.pid
    self._running = True
```

### 1.4 数据流

```
┌──────────────┐     ┌─────────────┐     ┌───────────────┐
│   WebSocket  │◄───►│  Bridge     │◄───►│ ClaudeSession │
│   Client     │     │  (sessions) │     │   (PTY)       │
└──────────────┘     └─────────────┘     └───────────────┘
       │                    │                    │
       │ ws/{name}          │                    │
       │───────────────────►│                    │
       │                    │ create_session()   │
       │                    │───────────────────►│
       │                    │                    │ start()
       │                    │                    │ fork/spawn
       │                    │                    │◄───────┐
       │                    │                    │        │ claude process
       │                    │                    │───────►│
       │                    │                    │        │
       │                    │ get_buffer()       │        │
       │                    │◄───────────────────│        │
       │                    │                    │        │
       │ connected + pid    │                    │        │
       │◄───────────────────│                    │        │
       │                    │                    │        │
       │ input (base64)     │                    │        │
       │───────────────────►│ send_input()       │        │
       │                    │───────────────────►│        │
       │                    │                    │ write  │
       │                    │                    │───────►│
       │                    │                    │        │
       │                    │ read_loop()        │        │
       │                    │◄───────────────────│ output │
       │ output (base64)    │                    │        │
       │◄───────────────────│                    │        │
```

### 1.5 会话状态

| 状态 | 判断方法 | 说明 |
|------|----------|------|
| alive | `is_alive()` | 进程正在运行 |
| dead | `not is_alive()` | 进程已退出 |
| attaching | `_attached` 标志 | 有 WebSocket 连接 |
| busy/idle | `_detect_claude_state()` | 基于输出分析 AI 状态 |

---

## 2. 本地终端创建流程

### 2.1 调用入口

| 入口 | WebSocket 路径 | 说明 |
|------|---------------|------|
| 前端连接 | `/ws/local/{name}` | 本地 Shell 会话 |

### 2.2 创建流程图

```
前端 WebSocket 连接
    │
    ▼
web/routes/ssh.py:ws_local_shell(websocket, name)
    │
    ├─► 接收初始化参数
    │   - rows, cols (终端尺寸)
    │   - shell (可选，覆盖默认)
    │
    ├─► Windows 平台 ──► _ws_local_shell_windows()
    │   1. 确定 Shell (powershell.exe 或 cmd.exe)
    │   2. subprocess.Popen() 创建进程
    │      - stdin/stdout/stderr 管道
    │      - creationflag=CREATE_NO_WINDOW (隐藏窗口)
    │   3. 启动 stdout_to_ws() 读取任务
    │   4. 启动 ws_to_stdin() 写入任务
    │
    └─► Unix 平台 ──► _ws_local_shell_unix()
        1. 检查断开的会话 (_get_disconnected_session)
        2. 如无可用会话，创建新 PTY:
           - pty.openpty() 创建主从端
           - os.fork() 创建子进程
           - 子进程：绑定 PTY，exec 执行 Shell
        3. 保存 master_fd 和 child_pid
        │
        └─► WebSocket 断开时
            └─► _save_disconnected_session() 保存资源
                (60 秒内可重连复用)
    │
    ▼
发送 connected 消息
    │ {"type": "connected", "name": name, "pid": pid}
    │
    ▼
双向桥接任务启动
    ├─► pty_to_ws() / stdout_to_ws() - 输出转发
    └─► ws_to_pty() / ws_to_stdin() - 输入转发
```

### 2.3 核心代码路径

```python
# 1. WebSocket 入口 (ssh.py:129-156)
@router.websocket("/ws/local/{name}")
async def ws_local_shell(websocket: WebSocket, name: str):
    await websocket.accept()

    # 接收初始化参数
    init = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    rows = int(init.get("rows", 24))
    cols = int(init.get("cols", 80))
    shell_override = init.get("shell")

    if IS_WINDOWS:
        await _ws_local_shell_windows(websocket, name, shell_override, rows, cols)
    else:
        await _ws_local_shell_unix(websocket, name, shell_override, rows, cols)

# 2. Unix PTY 实现 (ssh.py:250-344)
async def _ws_local_shell_unix(websocket, name, shell_override, rows, cols):
    # 检查断开的会话
    saved_sess = _get_disconnected_session(name)
    if saved_sess and "master_fd" in saved_sess:
        master_fd = saved_sess["master_fd"]
        child_pid = saved_sess["child_pid"]
        try:
            os.kill(child_pid, 0)  # 检查进程是否存在
            _remove_disconnected_session(name)  # 复用，从保存列表移除
        except OSError:
            saved_sess = None  # 进程已死，创建新的

    if not saved_sess:
        # 创建新 PTY
        shell = shell_override or _LOCAL_SHELL
        master_fd, slave_fd = pty.openpty()
        _fcntl.ioctl(master_fd, _termios.TIOCSWINSZ, winsize)

        child_pid = os.fork()
        if child_pid == 0:
            os.close(master_fd)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0); os.dup2(slave_fd, 1); os.dup2(slave_fd, 2)
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            os.execvpe(shell, [shell], env)
            os._exit(1)

        os.close(slave_fd)

    # 双向桥接
    await asyncio.gather(pty_to_ws(), ws_to_pty())

    # WebSocket 断开时保存会话
    _save_disconnected_session(name, master_fd=master_fd, child_pid=child_pid)

# 3. Windows 实现 (ssh.py:159-247)
async def _ws_local_shell_windows(websocket, name, shell_override, rows, cols):
    CREATE_NO_WINDOW = 0x08000000

    # 确定 Shell
    shell = shell_override or os.environ.get("COMSPEC", "cmd.exe")
    shell_args = ["/q"] if shell == "cmd.exe" else []

    process = subprocess.Popen(
        [shell] + shell_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
        env=os.environ.copy(),
    )

    # 双向桥接
    await asyncio.gather(stdout_to_ws(), ws_to_stdin())

    # 清理
    process.kill()
```

### 2.4 断开会话保持机制

```python
# ssh.py:91-98
def _save_disconnected_session(name: str, **kwargs):
    """保存断开的会话资源"""
    _cleanup_disconnected_sessions()  # 先清理超时的
    with _disconnected_sessions_lock:
        kwargs["disconnect_time"] = _time.time()
        _disconnected_sessions[name] = kwargs

# ssh.py:65-88
def _cleanup_disconnected_sessions():
    """清理超时的断开会话 (60 秒)"""
    now = _time.time()
    with _disconnected_sessions_lock:
        to_remove = []
        for name, sess in _disconnected_sessions.items():
            if now - sess["disconnect_time"] > _SESSION_KEEPALIVE_TIME:
                to_remove.append(name)
                # 清理资源
                os.close(sess["master_fd"])
                os.kill(sess["child_pid"], 9)
                os.waitpid(sess["child_pid"], 0)
        for name in to_remove:
            del _disconnected_sessions[name]
```

### 2.5 消息协议

```json
// 客户端 → 服务端
{"type": "input", "data": "<base64>"}      // 键盘输入
{"type": "resize", "rows": 24, "cols": 80} // 终端尺寸
{"type": "ping"}                           // 心跳

// 服务端 → 客户端
{"type": "output", "data": "<base64>"}     // 终端输出
{"type": "connected", "name": "..."}       // 连接成功
{"type": "exit"}                           // 会话结束
{"type": "pong"}                           // 心跳响应
```

---

## 3. 远程终端 (SSH) 创建流程

### 3.1 调用入口

| 入口 | WebSocket 路径 | 说明 |
|------|---------------|------|
| 前端连接 | `/ws/ssh/{name}` | SSH 远程会话 |

### 3.2 创建流程图

```
前端 WebSocket 连接
    │
    ▼
web/routes/ssh.py:ws_ssh(websocket, name)
    │
    ├─► 检查 paramiko 是否安装
    │   - 未安装：返回错误
    │
    ├─► 发送 waiting 消息
    │   {"type": "waiting", "message": "等待 SSH 连接参数…"}
    │
    ├─► 接收 SSH 连接参数 (15 秒超时)
    │   {
    │     "type": "ssh_connect",
    │     "host": "192.168.1.100",
    │     "port": 22,
    │     "username": "user",
    │     "password": "xxx" (可选),
    │     "key_path": "~/.ssh/id_rsa" (可选),
    │     "rows": 24, "cols": 80,
    │     "label": "显示名称",
    │     "save_password": false
    │   }
    │
    ▼
建立 SSH 连接
    │
    ├─► 创建 TCP 连接
    │   socket.create_connection((host, port), timeout=10)
    │
    ├─► 创建 Paramiko Transport
    │   transport = paramiko.Transport(sock)
    │   transport.start_client(timeout=10)
    │
    ├─► 认证
    │   ├─► 密钥认证 (key_path 指定)
    │   │   auth_publickey(username, pkey)
    │   │
    │   ├─► 密码认证 (password 指定)
    │   │   auth_password(username, password)
    │   │
    │   └─► Agent/默认密钥
    │       auth_publickey(username, agent_key)
    │       或尝试 ~/.ssh/id_rsa, id_ed25519...
    │
    ├─► 打开 Shell 通道
    │   chan = transport.open_session()
    │   chan.get_pty("xterm-256color", cols, rows)
    │   chan.invoke_shell()
    │   chan.setblocking(False)
    │
    ▼
保存到 SSH 历史
    │ _upsert_ssh_history(history_entry)
    │
    ▼
发送 connected 消息
    │ {"type": "connected", "name": name, "host": host, ...}
    │
    ▼
双向桥接任务启动
    ├─► ssh_read_task() - SSH → WebSocket
    └─► ws_read_task()  - WebSocket → SSH
```

### 3.3 核心代码路径

```python
# 1. WebSocket 入口 (ssh.py:373-486)
@router.websocket("/ws/ssh/{name}")
async def ws_ssh(websocket: WebSocket, name: str):
    if not _PARAMIKO_OK:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "paramiko not installed"})
        return

    await websocket.accept()
    await websocket.send_json({"type": "waiting", "message": "等待 SSH 连接参数…"})

    # 接收连接参数
    init_msg = await asyncio.wait_for(websocket.receive_json(), timeout=15)
    if init_msg.get("type") != "ssh_connect":
        raise Error("期望 ssh_connect 消息")

    host = init_msg.get("host", "")
    port = int(init_msg.get("port", 22))
    username = init_msg.get("username", "")
    password = init_msg.get("password", "")
    key_path = init_msg.get("key_path", "")

    # 建立 SSH 连接
    sock = socket.create_connection((host, port), timeout=10)
    transport = paramiko.Transport(sock)
    transport.start_client(timeout=10)

    # 认证
    if key_path:
        pkey = paramiko.RSAKey.from_private_key_file(kp)
        transport.auth_publickey(username, pkey)
    elif password:
        transport.auth_password(username, password)
    else:
        # 尝试 agent 或默认密钥
        ...

    # 打开 Shell
    chan = transport.open_session()
    chan.get_pty("xterm-256color", cols, rows)
    chan.invoke_shell()
    chan.setblocking(False)

    # 保存历史
    _upsert_ssh_history(history_entry, save_password)

    await websocket.send_json({"type": "connected", "name": name, ...})

    # 双向桥接
    await asyncio.gather(ssh_read_task(), ws_read_task())

# 2. SSH → WebSocket (ssh.py:490-512)
async def ssh_read_task():
    """SSH → WebSocket"""
    while not stop_ev.is_set():
        await asyncio.sleep(0.02)
        data = chan.recv(4096)
        if not data: break
        await websocket.send_json({
            "type": "output",
            "data": base64.b64encode(data).decode()
        })

# 3. WebSocket → SSH (ssh.py:514-534)
async def ws_read_task():
    """WebSocket → SSH"""
    while not stop_ev.is_set():
        msg = await websocket.receive_json()
        if msg.get("type") == "input":
            data = base64.b64decode(msg["data"])
            chan.send(data)
        elif msg.get("type") == "resize":
            r, c = rows, cols
            chan.resize_pty(c, r)
```

### 3.4 SSH 历史管理

```python
# ssh.py:116-126
def _upsert_ssh_history(entry: dict, save_password: bool = False):
    """添加或更新历史连接 (按 host,port,username 唯一键)"""
    with _ssh_history_lock:
        entries = _load_ssh_history()
        key = (entry["host"], entry.get("port", 22), entry["username"])
        # 移除旧记录
        entries = [e for e in entries if (e["host"], e.get("port", 22), e["username"]) != key]
        # 不保存密码则移除字段
        if not save_password:
            entry = {k: v for k, v in entry.items() if k != "password"}
        entries.insert(0, entry)
        _save_ssh_history(entries[:20])  # 保留最近 20 条
```

### 3.5 消息协议

```json
// 客户端 → 服务端 (初始化)
{
  "type": "ssh_connect",
  "host": "192.168.1.100",
  "port": 22,
  "username": "root",
  "password": "secret",
  "key_path": "~/.ssh/id_rsa",
  "label": "生产服务器",
  "save_password": false,
  "rows": 24,
  "cols": 80
}

// 客户端 → 服务端 (运行时)
{"type": "input", "data": "<base64>"}
{"type": "resize", "rows": 30, "cols": 100}
{"type": "ping"}

// 服务端 → 客户端
{"type": "waiting", "message": "等待 SSH 连接参数…"}
{"type": "connected", "name": "...", "host": "...", "username": "..."}
{"type": "output", "data": "<base64>"}
{"type": "exit"}
{"type": "error", "message": "..."}
{"type": "pong"}
```

---

## 4. 三种会话类型对比

| 特性 | Claude 会话 | 本地终端 | 远程终端 (SSH) |
|------|------------|----------|----------------|
| **进程类型** | claude (AI) | 本地 Shell | SSH Shell |
| **创建方式** | PTY/ConPTY | PTY/subprocess | Paramiko |
| **WebSocket 路径** | `/ws/{name}` | `/ws/local/{name}` | `/ws/ssh/{name}` |
| **平台差异** | Unix:PTY, Windows:winpty | Unix:PTY, Windows:subprocess | 跨平台 (paramiko) |
| **断连保持** | 否 (需手动重连) | 是 (60 秒) | 否 |
| **历史记录** | 会话日志文件 | 无 | SSH 历史列表 |
| **认证方式** | 无 | 无 | 密码/密钥/Agent |
| **依赖** | claude CLI | 系统 Shell | paramiko |
| **典型用途** | AI 编程助手 | 本地命令执行 | 远程服务器管理 |

---

## 5. 相关文件索引

### 5.1 核心文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `core/session.py` | 1-468 | Claude 会话核心实现 |
| `web/bridge.py` | 220-243 | 会话创建桥接函数 |
| `web/state.py` | 1-100+ | 全局状态管理 |
| `web/routes/sessions.py` | 1-115 | 会话 REST API |
| `web/routes/ssh.py` | 1-550 | SSH/本地终端实现 |
| `web/routes/cards.py` | 1-446 | 卡片管理 (含 Claude 卡片) |

### 5.2 状态管理

```python
# web/state.py 中的全局状态
_sessions: dict[str, ClaudeSession]      # Claude 会话池
_ssh_sessions: dict                       # SSH 会话 (未使用)
_disconnected_sessions: dict              # 断开的本地终端
_cards: list[dict]                        # 卡片配置
_feishu_bots: dict[str, FeishuBot]        # 飞书机器人
_telegram_bots: dict[str, TelegramBot]    # Telegram 机器人
...
```

### 5.3 数据持久化

| 文件 | 内容 |
|------|------|
| `~/.app/run/cards.json` | 卡片配置 |
| `~/.app/run/feishu.json` | 飞书凭证 |
| `~/.app/run/ssh_history.json` | SSH 连接历史 |
| `log/app_{session}_{ts}.log` | 会话日志 (人类可读) |
| `log/app_{session}_{ts}.raw` | 会话原始输出 (二进制) |
