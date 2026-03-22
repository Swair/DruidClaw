"""
PTY-based Claude Code session management.
Each session runs claude in a pseudo-terminal, intercepting all I/O.
"""
import os
import pty
import fcntl
import termios
import struct
import signal
import threading
import time
import select
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Default claude executable
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
LOG_DIR = Path(os.environ.get("DRUIDCLAW_LOG_DIR",
               str(Path(__file__).resolve().parent.parent.parent / "log")))


class IORecorder:
    """Records session I/O to a log file with timestamps."""

    def __init__(self, session_name: str, log_dir: Path = LOG_DIR):
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = log_dir / f"app_{session_name}_{ts}.log"
        self.raw_path = log_dir / f"app_{session_name}_{ts}.raw"
        self._log_f = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self._raw_f = open(self.raw_path, "wb")
        self._lock = threading.Lock()
        self.write_header(session_name)

    def write_header(self, name: str):
        ts = datetime.now().isoformat()
        self._log_f.write(f"# DruidClaw Session: {name}\n")
        self._log_f.write(f"# Started: {ts}\n")
        self._log_f.write(f"# {'='*60}\n\n")
        self._log_f.flush()

    def record_output(self, data: bytes):
        with self._lock:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            try:
                text = data.decode("utf-8", errors="replace")
                self._log_f.write(text)
                self._log_f.flush()
            except Exception:
                pass
            self._raw_f.write(data)
            self._raw_f.flush()

    def record_input(self, data: bytes):
        """Input is also logged (marked differently in raw log)."""
        with self._lock:
            # Write a marker byte sequence to raw (0x01 = input marker)
            self._raw_f.write(b"\x01" + data)
            self._raw_f.flush()

    def close(self):
        with self._lock:
            ts = datetime.now().isoformat()
            try:
                self._log_f.write(f"\n\n# Session ended: {ts}\n")
                self._log_f.close()
                self._raw_f.close()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class ClaudeSession:
    """
    Manages a single Claude Code process in a PTY.

    The session can be:
    - Running + attached: PTY connected to a real terminal
    - Running + detached: PTY kept alive, output buffered
    - Stopped: process exited
    """

    def __init__(
        self,
        name: str,
        workdir: str = ".",
        claude_args: list[str] = None,
        enable_recording: bool = True,
    ):
        self.name = name
        self.workdir = os.path.abspath(workdir)
        self.claude_args = claude_args or []
        self.created_at = datetime.now()

        self.pid: Optional[int] = None
        self.master_fd: Optional[int] = None  # PTY master
        self._child_pid: Optional[int] = None

        self._running = False
        self._attached = False
        self._attach_lock = threading.Lock()

        # Output buffer for when detached (ring buffer, 64KB)
        self._buf: bytearray = bytearray()
        self._buf_max = 64 * 1024
        self._buf_lock = threading.Lock()

        # Callbacks
        self._output_callbacks: list[Callable[[bytes], None]] = []

        # I/O recorder
        self.recorder: Optional[IORecorder] = None
        if enable_recording:
            self.recorder = IORecorder(name)

        # Background reader thread
        self._reader_thread: Optional[threading.Thread] = None

        # Terminal size tracking
        self._term_size = (24, 80)

    # ------------------------------------------------------------------ #
    #  Session lifecycle                                                   #
    # ------------------------------------------------------------------ #

    def start(self):
        """Fork a child process running claude inside a PTY."""
        if self._running:
            raise RuntimeError(f"Session '{self.name}' already running")

        cmd = [CLAUDE_BIN] + self.claude_args
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"

        # Create PTY pair
        self.master_fd, slave_fd = pty.openpty()

        # Set PTY size
        self._set_pty_size(self.master_fd, *self._term_size)

        # Fork child
        self._child_pid = os.fork()
        if self._child_pid == 0:
            # --- Child ---
            os.close(self.master_fd)
            # Set slave as controlling terminal
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            # Redirect stdio
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.chdir(self.workdir)
            os.execvpe(cmd[0], cmd, env)
            os._exit(1)  # Should not reach here

        # --- Parent ---
        os.close(slave_fd)
        self.pid = self._child_pid
        self._running = True

        logger.info(f"Session '{self.name}' started (pid={self.pid})")

        # Start background reader
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name=f"reader-{self.name}"
        )
        self._reader_thread.start()

    def stop(self, timeout: float = 3.0):
        """Stop the session gracefully."""
        if not self._running:
            return
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Wait for reader thread
        if self._reader_thread:
            self._reader_thread.join(timeout=timeout)
        self._running = False
        if self.recorder:
            self.recorder.close()
        logger.info(f"Session '{self.name}' stopped")

    def kill(self):
        """Force kill the session."""
        if self._running and self.pid:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self._running = False
        if self.recorder:
            self.recorder.close()

    def is_alive(self) -> bool:
        """Check if the child process is still running."""
        if not self._running or self.pid is None:
            return False
        try:
            result = os.waitpid(self.pid, os.WNOHANG)
            if result[0] != 0:
                self._running = False
                return False
            return True
        except ChildProcessError:
            self._running = False
            return False

    # ------------------------------------------------------------------ #
    #  Attach / Detach                                                     #
    # ------------------------------------------------------------------ #

    def attach(self, stdin_fd: int = 0, stdout_fd: int = 1):
        """
        Attach the calling terminal to this session.
        Blocks until detached (Ctrl-Z) or session exits.

        Returns True if session is still alive, False if it exited.
        """
        with self._attach_lock:
            if self._attached:
                raise RuntimeError(f"Session '{self.name}' already attached")
            self._attached = True

        # Sync terminal size
        try:
            rows, cols = _get_terminal_size(stdin_fd)
            self.resize(rows, cols)
        except Exception:
            pass

        # Put stdin into raw mode
        old_settings = None
        try:
            old_settings = termios.tcgetattr(stdin_fd)
            tty_raw(stdin_fd)
        except termios.error:
            pass

        # Install SIGWINCH handler to propagate resize
        old_sigwinch = signal.signal(signal.SIGWINCH, lambda s, f: self._on_winch(stdin_fd))

        # First, flush buffered output to the terminal
        with self._buf_lock:
            if self._buf:
                try:
                    os.write(stdout_fd, bytes(self._buf))
                except OSError:
                    pass
                self._buf.clear()

        # Register output callback to write to stdout
        def _write_to_terminal(data: bytes):
            try:
                os.write(stdout_fd, data)
            except OSError:
                pass

        self._output_callbacks.append(_write_to_terminal)

        alive = True
        try:
            while self._running and self.is_alive():
                r, _, _ = select.select([stdin_fd], [], [], 0.1)
                if r:
                    try:
                        data = os.read(stdin_fd, 1024)
                    except OSError:
                        break
                    if not data:
                        break
                    # Ctrl-Z (ASCII 26) = detach
                    if b"\x1a" in data:
                        parts = data.split(b"\x1a", 1)
                        if parts[0]:
                            self.send_input(parts[0])
                        print("\r\n[Detached from session]", flush=True)
                        break
                    self.send_input(data)
            else:
                alive = self.is_alive()
        finally:
            self._output_callbacks.remove(_write_to_terminal)
            self._attached = False
            signal.signal(signal.SIGWINCH, old_sigwinch)
            if old_settings is not None:
                try:
                    termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
                except termios.error:
                    pass

        return alive

    # ------------------------------------------------------------------ #
    #  I/O                                                                 #
    # ------------------------------------------------------------------ #

    def send_input(self, data: bytes):
        """Send raw bytes to the PTY (claude's stdin)."""
        if not self._running or self.master_fd is None:
            return
        if self.recorder:
            self.recorder.record_input(data)
        try:
            os.write(self.master_fd, data)
        except OSError as e:
            logger.warning(f"Failed to write to PTY: {e}")

    def send_text(self, text: str):
        """Send a text string as input."""
        self.send_input(text.encode())

    def send_line(self, line: str):
        """Send a line of text followed by Enter."""
        self.send_input((line + "\n").encode())

    def resize(self, rows: int, cols: int):
        """Resize the PTY."""
        self._term_size = (rows, cols)
        if self.master_fd is not None:
            try:
                self._set_pty_size(self.master_fd, rows, cols)
            except Exception:
                pass

    def get_buffer(self) -> bytes:
        """Get current output buffer (recent output while detached)."""
        with self._buf_lock:
            return bytes(self._buf)

    def add_output_callback(self, cb: Callable[[bytes], None]):
        self._output_callbacks.append(cb)

    def remove_output_callback(self, cb: Callable[[bytes], None]):
        try:
            self._output_callbacks.remove(cb)
        except ValueError:
            pass

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _reader_loop(self):
        """Background thread: read PTY output and dispatch."""
        while self._running:
            try:
                r, _, _ = select.select([self.master_fd], [], [], 0.5)
            except (ValueError, select.error):
                break
            if not r:
                if not self.is_alive():
                    break
                continue
            try:
                data = os.read(self.master_fd, 4096)
            except OSError:
                break
            if not data:
                break

            # Record output
            if self.recorder:
                self.recorder.record_output(data)

            # Always buffer recent output (ring buffer, used for reconnect)
            with self._buf_lock:
                self._buf.extend(data)
                if len(self._buf) > self._buf_max:
                    self._buf = self._buf[-self._buf_max:]

            # Call output callbacks (attached terminal / WebSocket)
            for cb in list(self._output_callbacks):
                try:
                    cb(data)
                except Exception:
                    pass

        # Reap child
        if self.pid:
            try:
                os.waitpid(self.pid, 0)
            except ChildProcessError:
                pass
        self._running = False
        if self.recorder:
            self.recorder.close()
        logger.info(f"Session '{self.name}' reader loop exited")

    def _set_pty_size(self, fd: int, rows: int, cols: int):
        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)

    def _on_winch(self, stdin_fd: int):
        try:
            rows, cols = _get_terminal_size(stdin_fd)
            self.resize(rows, cols)
        except Exception:
            pass

    def info(self) -> dict:
        return {
            "name": self.name,
            "pid": self.pid,
            "workdir": self.workdir,
            "alive": self.is_alive(),
            "attached": self._attached,
            "created_at": self.created_at.isoformat(),
            "log": str(self.recorder.log_path) if self.recorder else None,
            "buffer_bytes": len(self._buf),
        }

    def __repr__(self):
        status = "alive" if self.is_alive() else "dead"
        attached = " [attached]" if self._attached else ""
        return f"<ClaudeSession name={self.name!r} pid={self.pid} {status}{attached}>"


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

def tty_raw(fd: int):
    """Put terminal fd into raw mode."""
    attrs = termios.tcgetattr(fd)
    attrs[0] &= ~(
        termios.BRKINT | termios.ICRNL | termios.INPCK |
        termios.ISTRIP | termios.IXON
    )
    attrs[1] &= ~termios.OPOST
    attrs[2] &= ~(termios.CSIZE | termios.PARENB)
    attrs[2] |= termios.CS8
    attrs[3] &= ~(
        termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG
    )
    attrs[6][termios.VMIN] = 1
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def _get_terminal_size(fd: int) -> tuple[int, int]:
    size = struct.pack("HHHH", 0, 0, 0, 0)
    size = fcntl.ioctl(fd, termios.TIOCGWINSZ, size)
    rows, cols, _, _ = struct.unpack("HHHH", size)
    return max(rows, 24), max(cols, 80)
