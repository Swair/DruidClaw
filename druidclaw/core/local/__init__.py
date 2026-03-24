"""
Local terminal session management.

Provides local shell terminal functionality using PTY.
"""
import os
import threading
import logging
from datetime import datetime
from typing import Optional, Callable

from ..claude.pty_wrapper import PTYSession


logger = logging.getLogger(__name__)


class LocalSession:
    """
    Manages a local shell terminal session.

    Uses PTY to run a local shell process.
    """

    def __init__(
        self,
        name: str,
        workdir: str = ".",
        shell: str = None,
        shell_args: list[str] = None,
    ):
        self.name = name
        self.workdir = os.path.abspath(workdir)
        self.shell = shell or os.environ.get("SHELL", "/bin/bash")
        self.shell_args = shell_args or []
        self.created_at = datetime.now()

        self._attached = False
        self._attach_lock = threading.Lock()

        cmd = [self.shell] + self.shell_args
        self._pty_session = PTYSession(
            cmd=cmd,
            workdir=self.workdir,
            env={},
            rows=24,
            cols=80,
        )

    @property
    def pid(self) -> Optional[int]:
        return self._pty_session.pid

    @property
    def _running(self) -> bool:
        return self._pty_session._running

    @_running.setter
    def _running(self, value: bool):
        self._pty_session._running = value

    @property
    def _buf(self) -> bytearray:
        return self._pty_session._buf

    @_buf.setter
    def _buf(self, value: bytearray):
        self._pty_session._buf = value

    @property
    def _output_callbacks(self) -> list:
        return self._pty_session._output_callbacks

    @_output_callbacks.setter
    def _output_callbacks(self, value: list):
        self._pty_session._output_callbacks = value

    def start(self):
        """Start local shell session."""
        if self._running:
            raise RuntimeError(f"Session '{self.name}' already running")
        self._pty_session.start()
        logger.info(f"Local session '{self.name}' started (pid={self.pid})")

    def stop(self, timeout: float = 3.0):
        """Stop session gracefully."""
        self._pty_session.stop(timeout=timeout)
        logger.info(f"Local session '{self.name}' stopped")

    def kill(self):
        """Force kill session."""
        self._pty_session.kill()
        logger.info(f"Local session '{self.name}' killed")

    def is_alive(self) -> bool:
        """Check if process is still running."""
        return self._pty_session.is_alive()

    def send_input(self, data: bytes):
        """Send raw bytes to session stdin."""
        if not self._running:
            return
        self._pty_session.send_input(data)

    def send_text(self, text: str):
        """Send text string as input."""
        self.send_input(text.encode())

    def send_line(self, line: str):
        """Send line with Enter."""
        self.send_input((line + "\n").encode())

    def resize(self, rows: int, cols: int):
        """Resize terminal."""
        self._pty_session.resize(rows, cols)

    def get_buffer(self) -> bytes:
        """Get current output buffer."""
        return self._pty_session.get_buffer()

    def add_output_callback(self, cb: Callable[[bytes], None]):
        """Register output callback."""
        self._pty_session.add_output_callback(cb)

    def remove_output_callback(self, cb: Callable[[bytes], None]):
        """Remove output callback."""
        self._pty_session.remove_output_callback(cb)

    def info(self) -> dict:
        """Get session information."""
        return {
            "name": self.name,
            "pid": self.pid,
            "workdir": self.workdir,
            "alive": self.is_alive(),
            "attached": self._attached,
            "created_at": self.created_at.isoformat(),
            "buffer_bytes": len(self.get_buffer()),
        }

    def __repr__(self):
        status = "alive" if self.is_alive() else "dead"
        attached = " [attached]" if self._attached else ""
        return f"<LocalSession name={self.name!r} pid={self.pid} {status}{attached}>"


__all__ = ["LocalSession"]
