"""
DruidClaw Daemon: manages multiple ClaudeSession instances.
Exposes a Unix socket (or TCP on Windows) for IPC with cc client processes.

Protocol: newline-delimited JSON (request/response).
For "attach" command: bidirectional raw byte streaming after ack.
"""
import os
import sys
import json
import socket
import signal
import threading
import logging
import time
from pathlib import Path
from typing import Optional

# Platform detection
IS_WINDOWS = os.name == "nt"

if not IS_WINDOWS:
    import select

from .claude import ClaudeSession

logger = logging.getLogger(__name__)

# On Windows, use TCP socket instead of Unix socket
if IS_WINDOWS:
    RUN_DIR = Path(os.environ.get("DRUIDCLAW_RUN_DIR", Path.cwd() / "run"))
    SOCKET_PATH = None  # Not used on Windows
    TCP_HOST = "127.0.0.1"
    TCP_PORT = 19124  # Daemon IPC port
else:
    RUN_DIR = Path(os.environ.get("DRUIDCLAW_RUN_DIR", Path.cwd() / "run"))
    SOCKET_PATH = RUN_DIR / "daemon.sock"
    TCP_HOST = None
    TCP_PORT = None

PID_FILE = RUN_DIR / "daemon.pid"

# Detach signal (3 bytes 0xff from client)
DETACH_SIGNAL = b"\xff\xff\xff"


# Maximum number of concurrent sessions allowed
MAX_SESSIONS = 30


class CCDaemon:
    """
    Background daemon that manages Claude Code sessions.
    Clients connect via Unix socket and send JSON commands.
    """

    def __init__(self):
        self.sessions: dict[str, ClaudeSession] = {}
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._running = False

    # ------------------------------------------------------------------ #
    #  Daemon lifecycle                                                    #
    # ------------------------------------------------------------------ #

    def start(self):
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        if IS_WINDOWS:
            # Windows: use TCP socket
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((TCP_HOST, TCP_PORT))
            self._sock.listen(32)
            self._sock.settimeout(1.0)
            logger.info(f"CC Daemon started (pid={os.getpid()}) tcp={TCP_HOST}:{TCP_PORT}")
        else:
            # Unix: use Unix domain socket
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.bind(str(SOCKET_PATH))
            self._sock.listen(32)
            self._sock.settimeout(1.0)
            os.chmod(str(SOCKET_PATH), 0o600)
            logger.info(f"CC Daemon started (pid={os.getpid()}) socket={SOCKET_PATH}")

        self._running = True
        logger.info(f"CC Daemon started (pid={os.getpid()}) socket={SOCKET_PATH}")

        if not IS_WINDOWS:
            signal.signal(signal.SIGTERM, self._handle_sigterm)
            signal.signal(signal.SIGINT, self._handle_sigterm)
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)

        watchdog = threading.Thread(target=self._watchdog, daemon=True)
        watchdog.start()

        try:
            while self._running:
                try:
                    conn, _ = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                t = threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                )
                t.start()
        finally:
            self._shutdown()

    def _shutdown(self):
        logger.info("CC Daemon shutting down...")
        self._running = False
        with self._lock:
            for s in self.sessions.values():
                try:
                    s.stop()
                except Exception:
                    pass
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if not IS_WINDOWS and SOCKET_PATH:
            SOCKET_PATH.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        logger.info("CC Daemon stopped")

    def _handle_sigterm(self, sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        self._running = False
        # Force kill all sessions immediately on Ctrl+C/SIGTERM
        with self._lock:
            for name, s in list(self.sessions.items()):
                try:
                    logger.info(f"Killing session '{name}'...")
                    s.kill()
                except Exception as e:
                    logger.error(f"Error killing session '{name}': {e}")
            self.sessions.clear()
        logger.info("All sessions killed, daemon ready to shutdown")

    def _watchdog(self):
        while self._running:
            time.sleep(5)
            with self._lock:
                dead = [n for n, s in self.sessions.items() if not s.is_alive()]
            for name in dead:
                logger.info(f"Removing dead session '{name}'")
                with self._lock:
                    s = self.sessions.pop(name, None)
                if s:
                    try:
                        s.kill()  # Force kill the session
                    except Exception:
                        pass

    # ------------------------------------------------------------------ #
    #  Client handler                                                      #
    # ------------------------------------------------------------------ #

    def _handle_client(self, conn: socket.socket):
        buf = b""
        try:
            conn.settimeout(30)
            while True:
                if IS_WINDOWS:
                    # Windows: use recv() with timeout
                    conn.setblocking(False)
                    try:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    except BlockingIOError:
                        time.sleep(0.01)
                        continue
                else:
                    # Unix: use select()
                    r, _, _ = select.select([conn], [], [], 1.0)
                    if not r:
                        continue
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line)
                    except json.JSONDecodeError:
                        self._send_json(conn, {"error": "invalid JSON"})
                        continue
                    cmd = req.get("cmd", "")
                    if cmd == "attach":
                        # Switch to streaming mode
                        resp = self._cmd_attach_stream(req, conn)
                        return  # connection is done after attach
                    else:
                        resp = self._dispatch(req, conn)
                        if resp is not None:
                            self._send_json(conn, resp)
        except (OSError, ConnectionResetError):
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _send_json(self, conn: socket.socket, data: dict):
        try:
            conn.sendall(json.dumps(data).encode() + b"\n")
        except OSError:
            pass

    def _dispatch(self, req: dict, conn: socket.socket) -> Optional[dict]:
        cmd = req.get("cmd", "")
        handlers = {
            "new":    self._cmd_new,
            "list":   self._cmd_list,
            "info":   self._cmd_info,
            "kill":   self._cmd_kill,
            "input":  self._cmd_input,
            "buffer": self._cmd_buffer,
            "ping":   lambda r, c: {"pong": True},
        }
        handler = handlers.get(cmd)
        if handler is None:
            return {"error": f"unknown command: {cmd!r}"}
        try:
            return handler(req, conn)
        except Exception as e:
            logger.exception(f"Error handling cmd={cmd!r}")
            return {"error": str(e)}

    # ------------------------------------------------------------------ #
    #  Commands                                                            #
    # ------------------------------------------------------------------ #

    def _cmd_new(self, req: dict, conn) -> dict:
        name = req.get("name")
        workdir = req.get("workdir", ".")
        args = req.get("args", [])

        # Check max sessions limit
        with self._lock:
            if len(self.sessions) >= MAX_SESSIONS:
                return {"error": f"Maximum number of sessions ({MAX_SESSIONS}) reached"}

        if not name:
            with self._lock:
                idx = len(self.sessions) + 1
            name = f"session{idx}"
        with self._lock:
            if name in self.sessions:
                return {"error": f"session '{name}' already exists"}
        s = ClaudeSession(name=name, workdir=workdir, claude_args=args)
        try:
            s.start()
        except Exception as e:
            return {"error": f"failed to start: {e}"}
        with self._lock:
            self.sessions[name] = s
        return {"ok": True, "name": name, "pid": s.pid}

    def _cmd_list(self, req: dict, conn) -> dict:
        with self._lock:
            sessions = [s.info() for s in self.sessions.values()]
        return {"sessions": sessions}

    def _cmd_info(self, req: dict, conn) -> dict:
        name = req.get("name")
        with self._lock:
            s = self.sessions.get(name)
        if s is None:
            return {"error": f"session '{name}' not found"}
        return {"session": s.info()}

    def _cmd_kill(self, req: dict, conn) -> dict:
        name = req.get("name")
        force = req.get("force", False)
        with self._lock:
            s = self.sessions.pop(name, None)
        if s is None:
            return {"error": f"session '{name}' not found"}
        s.kill() if force else s.stop()
        return {"ok": True}

    def _cmd_input(self, req: dict, conn) -> dict:
        """Non-interactive input injection."""
        import base64
        name = req.get("name")
        with self._lock:
            s = self.sessions.get(name)
        if s is None:
            return {"error": f"session '{name}' not found"}
        data_b64 = req.get("data")
        text = req.get("text")
        line = req.get("line")
        if data_b64:
            s.send_input(base64.b64decode(data_b64))
        elif line is not None:
            s.send_line(str(line))
        elif text is not None:
            s.send_text(str(text))
        else:
            return {"error": "no input provided"}
        return {"ok": True}

    def _cmd_buffer(self, req: dict, conn) -> dict:
        import base64
        name = req.get("name")
        with self._lock:
            s = self.sessions.get(name)
        if s is None:
            return {"error": f"session '{name}' not found"}
        data = s.get_buffer()
        return {
            "data": base64.b64encode(data).decode(),
            "text": data.decode("utf-8", errors="replace"),
            "bytes": len(data),
        }

    def _cmd_attach_stream(self, req: dict, conn: socket.socket):
        """
        Bidirectional streaming attach.
        After ack, raw PTY output is forwarded to the socket,
        and raw socket input is forwarded to the PTY.
        Client sends DETACH_SIGNAL (0xff 0xff 0xff) to detach.
        """
        name = req.get("name")
        with self._lock:
            s = self.sessions.get(name)
        if s is None:
            self._send_json(conn, {"error": f"session '{name}' not found"})
            return
        if not s.is_alive():
            self._send_json(conn, {"error": f"session '{name}' is not alive"})
            return

        # Ack
        self._send_json(conn, {"ok": True, "name": name})
        conn.settimeout(None)

        stop_event = threading.Event()

        # PTY → socket
        def pty_to_sock(data: bytes):
            if stop_event.is_set():
                return
            try:
                conn.sendall(data)
            except OSError:
                stop_event.set()

        s.add_output_callback(pty_to_sock)

        # Flush current buffer to new client
        buf = s.get_buffer()
        if buf:
            try:
                conn.sendall(buf)
            except OSError:
                s.remove_output_callback(pty_to_sock)
                return

        # socket → PTY (in this thread)
        # Special frames (never valid UTF-8 in normal terminal use):
        #   DETACH:  b"\xff\xff\xff"         — client detach
        #   RESIZE:  b"\xff\xfe<R_hi><R_lo><C_hi><C_lo>"  — terminal resize
        RESIZE_PREFIX = b"\xff\xfe"

        def _process_incoming(buf: bytes) -> bytes:
            """Process special frames from buf, forward rest to PTY. Returns unprocessed tail."""
            while buf:
                # Detach
                if DETACH_SIGNAL in buf:
                    idx = buf.index(DETACH_SIGNAL)
                    if idx > 0:
                        s.send_input(buf[:idx])
                    stop_event.set()
                    return b""
                # Resize (6-byte frame: 2 magic + 2 rows + 2 cols)
                if RESIZE_PREFIX in buf:
                    idx = buf.index(RESIZE_PREFIX)
                    if idx > 0:
                        s.send_input(buf[:idx])
                        buf = buf[idx:]
                    if len(buf) >= 6:
                        rows = int.from_bytes(buf[2:4], "big")
                        cols = int.from_bytes(buf[4:6], "big")
                        s.resize(max(rows, 1), max(cols, 1))
                        buf = buf[6:]
                    else:
                        return buf  # wait for more data
                else:
                    s.send_input(buf)
                    return b""
            return b""

        incoming = b""
        try:
            while not stop_event.is_set() and s.is_alive():
                r, _, _ = select.select([conn], [], [], 0.5)
                if not r:
                    continue
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                incoming += chunk
                incoming = _process_incoming(incoming)
        finally:
            s.remove_output_callback(pty_to_sock)
            stop_event.set()
            try:
                conn.close()
            except Exception:
                pass
            logger.info(f"Client detached from session '{name}'")


# ------------------------------------------------------------------ #
#  Daemon entry point                                                  #
# ------------------------------------------------------------------ #

def run_daemon(foreground: bool = False):
    if not IS_WINDOWS and not foreground:
        _daemonize()

    RUN_DIR.mkdir(parents=True, exist_ok=True)

    # Setup logging
    log_file = RUN_DIR / "daemon.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(str(log_file), mode="a")],
    )

    daemon = CCDaemon()
    daemon.start()


def is_daemon_running() -> bool:
    if IS_WINDOWS:
        # Windows: try TCP connection
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((TCP_HOST, TCP_PORT))
            s.sendall(json.dumps({"cmd": "ping"}).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(256)
                if not chunk:
                    break
                buf += chunk
            s.close()
            if buf:
                r = json.loads(buf.split(b"\n")[0])
                return r.get("pong", False)
        except Exception:
            pass
        return False
    else:
        # Unix: check socket file
        if not SOCKET_PATH.exists():
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(str(SOCKET_PATH))
            s.sendall(json.dumps({"cmd": "ping"}).encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(256)
                if not chunk:
                    break
                buf += chunk
            s.close()
            if buf:
                r = json.loads(buf.split(b"\n")[0])
                return r.get("pong", False)
        except Exception:
            pass
        return False


def _daemonize():
    """Unix-only: fork into background daemon process."""
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    os.close(devnull)
