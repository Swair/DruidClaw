"""SSH and local shell WebSocket routes."""
import os
import sys
import json
import asyncio
import logging
import threading as _threading
import socket as _socket
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from druidclaw.web.state import (
    RUN_DIR,
    SSH_HISTORY_FILE,
    _ssh_sessions,
    _ssh_sessions_lock,
)

try:
    import paramiko as _paramiko
    _PARAMIKO_OK = True
except ImportError:
    _PARAMIKO_OK = False

router = APIRouter()

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# Windows: use powershell or cmd; Unix: use $SHELL or /bin/bash
if IS_WINDOWS:
    # Try powershell first, then cmd
    _LOCAL_SHELL = os.environ.get("COMSPEC", "cmd.exe")
    if os.path.exists(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"):
        _LOCAL_SHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
else:
    _LOCAL_SHELL = os.environ.get("SHELL", "/bin/bash")
_ssh_history_lock = _threading.Lock()

# 保存断开的会话资源，用于页面刷新后重连
# {session_name: {"master_fd": int, "child_pid": int, "transport": obj, "chan": obj, "disconnect_time": float}}
_disconnected_sessions: Dict[str, Dict[str, Any]] = {}
_disconnected_sessions_lock = _threading.Lock()
_SESSION_KEEPALIVE_TIME = 60  # 断连后保持 60 秒


def _load_ssh_history() -> list[dict]:
    if SSH_HISTORY_FILE.exists():
        try:
            return json.loads(SSH_HISTORY_FILE.read_text())
        except Exception:
            pass
    return []


def _save_ssh_history(entries: list[dict]):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    SSH_HISTORY_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


def _cleanup_disconnected_sessions():
    """清理超时的断开会话"""
    import time as _time
    now = _time.time()
    with _disconnected_sessions_lock:
        to_remove = []
        for name, sess in _disconnected_sessions.items():
            if now - sess["disconnect_time"] > _SESSION_KEEPALIVE_TIME:
                to_remove.append(name)
                # 清理资源
                try:
                    if "master_fd" in sess:
                        os.close(sess["master_fd"])
                    if "child_pid" in sess:
                        os.kill(sess["child_pid"], 9)
                        os.waitpid(sess["child_pid"], 0)
                    if "transport" in sess and sess["transport"]:
                        sess["transport"].close()
                    if "chan" in sess and sess["chan"]:
                        sess["chan"].close()
                except Exception as e:
                    logger.debug(f"Cleanup session {name} error: {e}")
        for name in to_remove:
            del _disconnected_sessions[name]


def _save_disconnected_session(name: str, **kwargs):
    """保存断开的会话资源"""
    import time as _time
    _cleanup_disconnected_sessions()  # 先清理超时的
    with _disconnected_sessions_lock:
        kwargs["disconnect_time"] = _time.time()
        _disconnected_sessions[name] = kwargs
        logger.info(f"Session '{name}' disconnected, keeping alive for {_SESSION_KEEPALIVE_TIME}s")


def _get_disconnected_session(name: str) -> Optional[Dict[str, Any]]:
    """获取保存的会话资源"""
    _cleanup_disconnected_sessions()
    with _disconnected_sessions_lock:
        return _disconnected_sessions.get(name)


def _remove_disconnected_session(name: str):
    """移除保存的会话资源（清理）"""
    with _disconnected_sessions_lock:
        sess = _disconnected_sessions.pop(name, None)
        if sess:
            logger.info(f"Session '{name}' removed, cleaning up resources")


def _upsert_ssh_history(entry: dict, save_password: bool = False):
    """Add or update entry by (host, port, username). Keeps last 20."""
    with _ssh_history_lock:
        entries = _load_ssh_history()
        key = (entry["host"], entry.get("port", 22), entry["username"])
        entries = [e for e in entries if (e["host"], e.get("port", 22), e["username"]) != key]
        # Remove password if not saving
        if not save_password:
            entry = {k: v for k, v in entry.items() if k != "password"}
        entries.insert(0, entry)
        _save_ssh_history(entries[:20])


@router.websocket("/ws/local/{name}")
async def ws_local_shell(websocket: WebSocket, name: str):
    """
    WebSocket ↔ local shell PTY (bash/sh).
    Identical protocol to the Claude PTY bridge but launches $SHELL.
    """
    import pty as _pty, fcntl as _fcntl, termios as _termios, struct as _struct, select as _select
    import base64 as _b64
    import time as _time

    await websocket.accept()

    # 检查是否有断开的会话可以复用
    saved_sess = _get_disconnected_session(name)
    if saved_sess and "master_fd" in saved_sess and "child_pid" in saved_sess:
        # 复用现有 PTY
        master_fd = saved_sess["master_fd"]
        child_pid = saved_sess["child_pid"]
        # 验证进程是否还活着
        try:
            os.kill(child_pid, 0)  # 信号 0 只检查进程是否存在
            logger.info(f"Reusing existing PTY session '{name}' (pid={child_pid})")
            _remove_disconnected_session(name)  # 从保存列表中移除，但不关闭资源
        except OSError:
            logger.info(f"Existing PTY session '{name}' is dead, creating new one")
            saved_sess = None

    if not saved_sess:
        # 创建新的 PTY
        rows, cols = 24, 80
        # Receive optional init params
        try:
            init = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            if init.get("type") == "local_connect":
                rows = int(init.get("rows", 24))
                cols = int(init.get("cols", 80))
        except Exception:
            pass

        # Fork a local PTY
        master_fd, slave_fd = _pty.openpty()
        # Set PTY size
        winsize = _struct.pack("HHHH", rows, cols, 0, 0)
        _fcntl.ioctl(master_fd, _termios.TIOCSWINSZ, winsize)

        child_pid = os.fork()
        if child_pid == 0:
            os.close(master_fd)
            os.setsid()
            _fcntl.ioctl(slave_fd, _termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0); os.dup2(slave_fd, 1); os.dup2(slave_fd, 2)
            if slave_fd > 2: os.close(slave_fd)
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            os.execvpe(_LOCAL_SHELL, [_LOCAL_SHELL], env)
            os._exit(1)

        os.close(slave_fd)
        logger.info(f"Created new PTY session '{name}' (pid={child_pid})")

    await websocket.send_json({"type": "connected", "name": name, "pid": child_pid})

    loop = asyncio.get_event_loop()
    stop_ev = asyncio.Event()

    async def pty_to_ws():
        while not stop_ev.is_set():
            try:
                rlist, _, _ = await loop.run_in_executor(
                    None, lambda: _select.select([master_fd], [], [], 0.1))
                if rlist:
                    data = os.read(master_fd, 4096)
                    if not data: break
                    await websocket.send_json({"type": "output",
                                               "data": _b64.b64encode(data).decode()})
            except Exception: break
        stop_ev.set()
        try: await websocket.send_json({"type": "exit"})
        except Exception: pass

    async def ws_to_pty():
        try:
            while not stop_ev.is_set():
                msg = await websocket.receive_json()
                if msg.get("type") == "input":
                    os.write(master_fd, _b64.b64decode(msg["data"]))
                elif msg.get("type") == "resize":
                    r, c = max(int(msg.get("rows",24)),1), max(int(msg.get("cols",80)),1)
                    _fcntl.ioctl(master_fd, _termios.TIOCSWINSZ,
                                 _struct.pack("HHHH", r, c, 0, 0))
        except WebSocketDisconnect: pass
        except Exception: pass
        finally: stop_ev.set()

    try:
        await asyncio.gather(pty_to_ws(), ws_to_pty())
    except Exception:
        pass
    finally:
        stop_ev.set()
        # WebSocket 断开时，保存会话资源而不是立即清理
        logger.info(f"WebSocket disconnected for session '{name}', saving resources")
        _save_disconnected_session(name, master_fd=master_fd, child_pid=child_pid)


class SSHConnectRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    password: str = ""
    key_path: str = ""
    label: str = ""
    session_name: str = ""   # name for this terminal session; auto-generated if empty


@router.get("/api/ssh/history")
def api_ssh_history():
    entries = _load_ssh_history()
    return {"history": entries}


@router.delete("/api/ssh/history/{idx}")
def api_ssh_history_delete(idx: int):
    with _ssh_history_lock:
        entries = _load_ssh_history()
        if 0 <= idx < len(entries):
            entries.pop(idx)
            _save_ssh_history(entries)
    return {"ok": True}


@router.websocket("/ws/ssh/{name}")
async def ws_ssh(websocket: WebSocket, name: str):
    """
    WebSocket ↔ SSH PTY bridge.
    The client first sends a 'connect' message with SSH credentials,
    then the protocol is identical to the local PTY bridge.
    """
    if not _PARAMIKO_OK:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "paramiko not installed"})
        await websocket.close()
        return

    await websocket.accept()
    await websocket.send_json({"type": "waiting", "message": "等待 SSH 连接参数…"})

    # Receive connection params
    try:
        init_msg = await asyncio.wait_for(websocket.receive_json(), timeout=15)
    except Exception:
        await websocket.send_json({"type": "error", "message": "连接超时"})
        await websocket.close()
        return

    if init_msg.get("type") != "ssh_connect":
        await websocket.send_json({"type": "error", "message": "期望 ssh_connect 消息"})
        await websocket.close()
        return

    host      = init_msg.get("host", "")
    port      = int(init_msg.get("port", 22))
    username  = init_msg.get("username", "")
    password  = init_msg.get("password", "")
    key_path  = init_msg.get("key_path", "")
    rows      = int(init_msg.get("rows", 24))
    cols      = int(init_msg.get("cols", 80))

    if not host or not username:
        await websocket.send_json({"type": "error", "message": "缺少 host 或 username"})
        await websocket.close()
        return

    # Establish SSH connection
    import base64
    transport = None
    chan = None
    try:
        sock = _socket.create_connection((host, port), timeout=10)
        transport = _paramiko.Transport(sock)
        transport.start_client(timeout=10)

        # Auth
        if key_path:
            kp = os.path.expanduser(key_path)
            pkey = _paramiko.RSAKey.from_private_key_file(kp)
            transport.auth_publickey(username, pkey)
        elif password:
            transport.auth_password(username, password)
        else:
            # Try agent / default keys
            agent = _paramiko.Agent()
            agent_keys = agent.get_keys()
            authed = False
            for key in agent_keys:
                try:
                    transport.auth_publickey(username, key)
                    authed = True
                    break
                except Exception:
                    pass
            if not authed:
                for kname in ("~/.ssh/id_rsa", "~/.ssh/id_ed25519", "~/.ssh/id_ecdsa"):
                    kp = os.path.expanduser(kname)
                    if os.path.exists(kp):
                        try:
                            pkey = _paramiko.RSAKey.from_private_key_file(kp)
                            transport.auth_publickey(username, pkey)
                            authed = True
                            break
                        except Exception:
                            pass
                if not authed:
                    raise Exception("无可用认证方式（无密码、无密钥、无 SSH agent）")

        if not transport.is_authenticated():
            raise Exception("认证失败")

        chan = transport.open_session()
        chan.get_pty("xterm-256color", cols, rows)
        chan.invoke_shell()
        chan.setblocking(False)

    except Exception as e:
        if transport:
            try: transport.close()
            except Exception: pass
        await websocket.send_json({"type": "error", "message": f"SSH 连接失败: {e}"})
        await websocket.close()
        return

    # Save to history
    label = init_msg.get("label", "") or f"{username}@{host}"
    save_password = init_msg.get("save_password", False)
    history_entry = {
        "host": host, "port": port, "username": username,
        "key_path": key_path, "label": label,
    }
    if save_password and password:
        history_entry["password"] = password
    _upsert_ssh_history(history_entry, save_password)

    await websocket.send_json({"type": "connected", "name": name,
                               "host": host, "username": username})

    loop = asyncio.get_event_loop()
    stop_ev = asyncio.Event()

    async def ssh_read_task():
        """SSH → WebSocket"""
        try:
            while not stop_ev.is_set():
                await asyncio.sleep(0.02)
                try:
                    data = chan.recv(4096)
                    if not data:
                        break
                    await websocket.send_json({
                        "type": "output",
                        "data": base64.b64encode(data).decode()
                    })
                except _socket.timeout:
                    pass
                except Exception:
                    break
        finally:
            stop_ev.set()
            try:
                await websocket.send_json({"type": "exit"})
            except Exception:
                pass

    async def ws_read_task():
        """WebSocket → SSH"""
        try:
            while not stop_ev.is_set():
                msg = await websocket.receive_json()
                mtype = msg.get("type", "")
                if mtype == "input":
                    data = base64.b64decode(msg["data"])
                    chan.send(data)
                elif mtype == "resize":
                    r = max(int(msg.get("rows", 24)), 1)
                    c = max(int(msg.get("cols", 80)), 1)
                    chan.resize_pty(c, r)
                elif mtype == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug(f"ws_read_task error: {e}")
        finally:
            stop_ev.set()

    try:
        await asyncio.gather(ssh_read_task(), ws_read_task())
    except Exception as e:
        logger.debug(f"SSH session error: {e}")
    finally:
        stop_ev.set()
        # 清理 SSH 资源
        if chan:
            try: chan.close()
            except Exception: pass
        if transport:
            try: transport.close()
            except Exception: pass
        logger.info(f"SSH session closed: {host}:{port} as {username}")
