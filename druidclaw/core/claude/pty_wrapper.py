"""
Unix PTY session implementation for Claude Code.

This module provides Unix-specific PTY-based session management.
"""
import os
import signal
import select
import threading
import logging
from typing import Optional, Callable

from .pty_utils import (
    create_pty_pair,
    set_pty_size,
    fork_child,
    get_terminal_size,
    set_terminal_raw_mode,
    restore_terminal_mode,
)


logger = logging.getLogger(__name__)

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")


class PTYSession:
    """
    Unix PTY-based session for running Claude Code.

    Manages a single process running in a pseudo-terminal.
    """

    def __init__(
        self,
        cmd: list[str] = None,
        workdir: str = ".",
        env: dict = None,
        rows: int = 24,
        cols: int = 80,
    ):
        self.cmd = cmd or [CLAUDE_BIN]
        self.workdir = os.path.abspath(workdir)
        self.env = env or {}
        self._term_size = (rows, cols)

        self.pid: Optional[int] = None
        self.master_fd: Optional[int] = None
        self._child_pid: Optional[int] = None

        self._running = False
        self._buf: bytearray = bytearray()
        self._buf_max = 64 * 1024
        self._buf_lock = threading.Lock()

        self._output_callbacks: list[Callable[[bytes], None]] = []
        self._reader_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the session process."""
        if self._running:
            raise RuntimeError("Session already running")

        env = os.environ.copy()
        env.update(self.env)
        env["TERM"] = "xterm-256color"

        master_fd, slave_fd = create_pty_pair()
        set_pty_size(master_fd, *self._term_size)

        child_pid = fork_child(master_fd, slave_fd, self.workdir, self.cmd, env)

        os.close(slave_fd)
        self.pid = child_pid
        self._child_pid = child_pid
        self.master_fd = master_fd
        self._running = True

        logger.info(f"Session started (pid={self.pid})")

        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name=f"reader-{self.pid}"
        )
        self._reader_thread.start()

    def stop(self, timeout: float = 3.0):
        """Stop session gracefully."""
        if not self._running:
            return
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if self._reader_thread:
            self._reader_thread.join(timeout=timeout)
        self._running = False
        logger.info("Session stopped")

    def kill(self):
        """Force kill session."""
        if not self._running:
            return
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self._running = False

    def is_alive(self) -> bool:
        """Check if process is still running."""
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

    def send_input(self, data: bytes):
        """Send raw bytes to session stdin."""
        if not self._running or self.master_fd is None:
            return
        try:
            os.write(self.master_fd, data)
        except OSError as e:
            logger.warning(f"Failed to write to PTY: {e}")

    def resize(self, rows: int, cols: int):
        """Resize terminal."""
        self._term_size = (rows, cols)
        if self.master_fd is not None:
            set_pty_size(self.master_fd, rows, cols)

    def get_buffer(self) -> bytes:
        """Get current output buffer."""
        with self._buf_lock:
            return bytes(self._buf)

    def add_output_callback(self, cb: Callable[[bytes], None]):
        """Register output callback."""
        self._output_callbacks.append(cb)

    def remove_output_callback(self, cb: Callable[[bytes], None]):
        """Remove output callback."""
        try:
            self._output_callbacks.remove(cb)
        except ValueError:
            pass

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

            with self._buf_lock:
                self._buf.extend(data)
                if len(self._buf) > self._buf_max:
                    self._buf = self._buf[-self._buf_max :]

            for cb in list(self._output_callbacks):
                try:
                    cb(data)
                except Exception:
                    pass

        if self.pid:
            try:
                os.waitpid(self.pid, 0)
            except ChildProcessError:
                pass
        self._running = False
        logger.info("Reader loop exited")


__all__ = ["PTYSession"]
