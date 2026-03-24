"""
DruidClaw Client: connects to the daemon via Unix socket.
Also implements direct attach (bypass daemon) for single-session use.
"""
import os
import sys
import json
import socket
import select
import struct
import signal
import base64
import threading
import time
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import msvcrt
else:
    import fcntl
    import termios

from .daemon import SOCKET_PATH, RUN_DIR, IS_WINDOWS, TCP_HOST, TCP_PORT


class DaemonClient:
    """Thin client for sending commands to the CC daemon."""

    def __init__(self, socket_path: Path = SOCKET_PATH):
        self.socket_path = socket_path
        self._sock: Optional[socket.socket] = None

    def connect(self, timeout: float = 5.0):
        if IS_WINDOWS:
            # Windows: use TCP socket
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            self._sock.connect((TCP_HOST, TCP_PORT))
        else:
            # Unix: use Unix domain socket
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            self._sock.connect(str(self.socket_path))

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send(self, cmd: dict) -> dict:
        """Send a command and return the response."""
        data = json.dumps(cmd).encode() + b"\n"
        self._sock.sendall(data)
        # Read response (newline-delimited JSON)
        buf = b""
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Daemon closed connection")
            buf += chunk
            if b"\n" in buf:
                line, _ = buf.split(b"\n", 1)
                return json.loads(line)

    def ping(self) -> bool:
        try:
            r = self.send({"cmd": "ping"})
            return r.get("pong", False)
        except Exception:
            return False

    def new_session(self, name: Optional[str] = None, workdir: str = ".", args: list = None) -> dict:
        req = {"cmd": "new", "workdir": workdir, "args": args or []}
        if name:
            req["name"] = name
        return self.send(req)

    def list_sessions(self) -> list:
        r = self.send({"cmd": "list"})
        return r.get("sessions", [])

    def session_info(self, name: str) -> dict:
        return self.send({"cmd": "info", "name": name})

    def kill_session(self, name: str, force: bool = False) -> dict:
        return self.send({"cmd": "kill", "name": name, "force": force})

    def send_input(self, name: str, text: str = None, line: str = None, data: bytes = None) -> dict:
        req = {"cmd": "input", "name": name}
        if data is not None:
            req["data"] = base64.b64encode(data).decode()
        elif line is not None:
            req["line"] = line
        elif text is not None:
            req["text"] = text
        return self.send(req)

    def get_buffer(self, name: str) -> dict:
        return self.send({"cmd": "buffer", "name": name})

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()


# ------------------------------------------------------------------ #
#  Terminal attach (for interactive use)                              #
# ------------------------------------------------------------------ #

def attach_to_session(name: str, client: "DaemonClient | None" = None):
    """
    Attach the current terminal to a session managed by the daemon.

    On Unix: uses Unix domain sockets with PTY.
    On Windows: uses TCP sockets with console I/O.

    Protocol:
      Client sends: {"cmd": "attach", "name": "..."}
      Daemon responds: {"ok": true}
      Then raw bytes are streamed bidirectionally.
      Client sends: b"\xff\xff\xff" to detach.
    """
    if IS_WINDOWS:
        _attach_to_session_windows(name, client)
    else:
        _attach_to_session_unix(name, client)


def _attach_to_session_windows(name: str, client: "DaemonClient | None" = None):
    """Windows-specific attach using TCP socket and console I/O."""
    # Use TCP connection for Windows
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("localhost", 19124))

    # Send attach command
    msg = json.dumps({"cmd": "attach", "name": name}).encode() + b"\n"
    sock.sendall(msg)

    # Read ack
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(256)
    line, _ = buf.split(b"\n", 1)
    ack = json.loads(line)
    if "error" in ack:
        sock.close()
        print(f"Error: {ack['error']}", file=sys.stderr)
        return

    print(f"[Attached to '{name}' -- press Ctrl-Z to detach, Ctrl-C to kill session]\r")

    stop_event = threading.Event()

    def reader():
        """Read from socket, write to stdout."""
        while not stop_event.is_set():
            try:
                data = sock.recv(4096)
                if not data:
                    stop_event.set()
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except OSError:
                stop_event.set()
                break

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    try:
        while not stop_event.is_set():
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char == '\x1a':  # Ctrl-Z = detach
                    try:
                        sock.sendall(b"\xff\xff\xff")
                    except OSError:
                        pass
                    print("\r\n[Detached]", flush=True)
                    break
                sock.sendall(char.encode('utf-8'))
            time.sleep(0.05)  # Prevent CPU spinning
    except KeyboardInterrupt:
        # Ctrl-C pressed — kill the session before detaching
        print("\r\n[Ctrl-C detected — killing session...]", flush=True)
        try:
            # Send detach signal first
            sock.sendall(b"\xff\xff\xff")
        except OSError:
            pass
        # Now send a command to daemon to kill the session
        try:
            cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            cmd_sock.connect((TCP_HOST, TCP_PORT))
            cmd_sock.sendall(json.dumps({"cmd": "kill", "name": name, "force": True}).encode() + b"\n")
            cmd_sock.close()
        except Exception:
            pass
        print("[Session killed]", flush=True)
    finally:
        stop_event.set()
        reader_thread.join(timeout=1)
        sock.close()


def _attach_to_session_unix(name: str, client: "DaemonClient | None" = None):
    """Unix-specific attach using Unix domain socket and PTY."""
    import select
    import signal

    # We need a separate connection for the streaming attach
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(SOCKET_PATH))

    # Send attach command
    msg = json.dumps({"cmd": "attach", "name": name}).encode() + b"\n"
    sock.sendall(msg)
    # Read ack
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(256)
    line, _ = buf.split(b"\n", 1)
    ack = json.loads(line)
    if "error" in ack:
        sock.close()
        print(f"Error: {ack['error']}", file=sys.stderr)
        return

    print(f"[Attached to '{name}' — press Ctrl-Z to detach, Ctrl-C to kill session]\r")

    # Put terminal in raw mode
    old_settings = None
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    try:
        old_settings = termios.tcgetattr(stdin_fd)
        _tty_raw(stdin_fd)
    except termios.error:
        pass

    # Send initial terminal size via resize magic frame
    # Frame: \xff\xfe + 2-byte rows (BE) + 2-byte cols (BE)
    def send_resize():
        try:
            rows, cols = _get_terminal_size(stdin_fd)
            frame = b"\xff\xfe" + rows.to_bytes(2, "big") + cols.to_bytes(2, "big")
            sock.sendall(frame)
        except Exception:
            pass

    send_resize()

    stop_event = threading.Event()

    # SIGWINCH → forward resize to daemon
    old_sigwinch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, lambda s, f: send_resize())

    def reader():
        """Read from socket, write to stdout."""
        while not stop_event.is_set():
            r, _, _ = select.select([sock], [], [], 0.2)
            if r:
                try:
                    data = sock.recv(4096)
                    if not data:
                        stop_event.set()
                        break
                    os.write(stdout_fd, data)
                except OSError:
                    stop_event.set()
                    break

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    try:
        while not stop_event.is_set():
            r, _, _ = select.select([stdin_fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(stdin_fd, 1024)
                except OSError:
                    break
                if not data:
                    break
                if b"\x1a" in data:
                    # Ctrl-Z = detach
                    before = data.split(b"\x1a", 1)[0]
                    if before:
                        sock.sendall(before)
                    # Send detach signal
                    try:
                        sock.sendall(b"\xff\xff\xff")
                    except OSError:
                        pass
                    print("\r\n[Detached]", flush=True)
                    break
                try:
                    sock.sendall(data)
                except OSError:
                    break
    except KeyboardInterrupt:
        # Ctrl-C pressed — kill the session before detaching
        print("\r\n[Ctrl-C detected — killing session...]", flush=True)
        try:
            # Send detach signal first so daemon knows we're done
            sock.sendall(b"\xff\xff\xff")
        except OSError:
            pass
        # Now send a command to daemon to kill the session
        try:
            cmd_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            cmd_sock.connect(str(SOCKET_PATH))
            cmd_sock.sendall(json.dumps({"cmd": "kill", "name": name, "force": True}).encode() + b"\n")
            cmd_sock.close()
        except Exception:
            pass
        print("[Session killed]", flush=True)
    finally:
        stop_event.set()
        signal.signal(signal.SIGWINCH, old_sigwinch)
        reader_thread.join(timeout=1)
        if old_settings is not None:
            try:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
            except termios.error:
                pass
        sock.close()


def _tty_raw(fd: int):
    attrs = termios.tcgetattr(fd)
    attrs[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
    attrs[1] &= ~termios.OPOST
    attrs[2] &= ~(termios.CSIZE | termios.PARENB)
    attrs[2] |= termios.CS8
    attrs[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
    attrs[6][termios.VMIN] = 1
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def _get_terminal_size(fd: int) -> tuple:
    size = struct.pack("HHHH", 0, 0, 0, 0)
    size = fcntl.ioctl(fd, termios.TIOCGWINSZ, size)
    rows, cols, _, _ = struct.unpack("HHHH", size)
    return max(rows, 24), max(cols, 80)
