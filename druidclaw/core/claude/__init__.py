"""
Claude Code session management.

High-level session management for Claude Code, built on top of the
cross-platform PTY abstraction layer (pty_wrapper).

This module is platform-agnostic - all OS-specific code is in pty_wrapper.py.
"""
import os
import threading
import logging
import signal
import termios
import struct
import select
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from .pty_wrapper import PTYSession


logger = logging.getLogger(__name__)

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
LOG_DIR = Path(os.environ.get("DRUIDCLAW_LOG_DIR",
               str(Path(__file__).resolve().parent.parent.parent.parent / "log")))


class IORecorder:
    """Records session I/O to a log file with timestamps."""

    FLUSH_INTERVAL = 20

    def __init__(self, session_name: str, log_dir: Path = LOG_DIR):
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = log_dir / f"app_{session_name}_{ts}.log"
        self.raw_path = log_dir / f"app_{session_name}_{ts}.raw"
        self._log_f = open(self.log_path, "w", encoding="utf-8", errors="replace", buffering=1)
        self._raw_f = open(self.raw_path, "wb", buffering=0)
        self._lock = threading.Lock()
        self._write_count = 0
        self.write_header(session_name)

    def write_header(self, name: str):
        ts = datetime.now().isoformat()
        self._log_f.write(f"# DruidClaw Session: {name}\n")
        self._log_f.write(f"# Started: {ts}\n")
        self._log_f.write(f"# {'='*60}\n\n")
        self._log_f.flush()

    def record_output(self, data: bytes):
        with self._lock:
            try:
                text = data.decode("utf-8", errors="replace")
                self._log_f.write(text)
            except Exception:
                pass
            self._raw_f.write(data)
            self._write_count += 1
            if self._write_count % self.FLUSH_INTERVAL == 0:
                self._log_f.flush()
                self._raw_f.flush()

    def record_input(self, data: bytes):
        with self._lock:
            self._raw_f.write(b"\x01" + data)
            self._write_count += 1
            if self._write_count % self.FLUSH_INTERVAL == 0:
                self._raw_f.flush()

    def close(self):
        with self._lock:
            ts = datetime.now().isoformat()
            try:
                self._log_f.flush()
                self._raw_f.flush()
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
    Manages a single Claude Code session.

    This is a high-level wrapper around PTYSession that adds:
    - I/O recording (logging)
    - Session metadata (name, workdir, created_at)
    - Output buffering for detached viewing
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

        self._attached = False
        self._attach_lock = threading.Lock()

        self.recorder: Optional[IORecorder] = None
        if enable_recording:
            self.recorder = IORecorder(name)

        cmd = [CLAUDE_BIN] + self.claude_args
        self._pty_session = PTYSession(
            cmd=cmd,
            workdir=self.workdir,
            env={},
            rows=24,
            cols=80,
        )

    @property
    def _running(self) -> bool:
        return self._pty_session._running

    @_running.setter
    def _running(self, value: bool):
        self._pty_session._running = value

    @property
    def pid(self) -> Optional[int]:
        return self._pty_session.pid

    @property
    def _reader_thread(self) -> Optional[threading.Thread]:
        return self._pty_session._reader_thread

    @_reader_thread.setter
    def _reader_thread(self, value: Optional[threading.Thread]):
        self._pty_session._reader_thread = value

    @property
    def _output_callbacks(self) -> list:
        return self._pty_session._output_callbacks

    @_output_callbacks.setter
    def _output_callbacks(self, value: list):
        self._pty_session._output_callbacks = value

    @property
    def _buf(self) -> bytearray:
        return self._pty_session._buf

    @_buf.setter
    def _buf(self, value: bytearray):
        self._pty_session._buf = value

    @property
    def _buf_lock(self) -> threading.Lock:
        return self._pty_session._buf_lock

    @_buf_lock.setter
    def _buf_lock(self, value: threading.Lock):
        self._pty_session._buf_lock = value

    def start(self):
        """Start Claude Code process."""
        if self._running:
            raise RuntimeError(f"Session '{self.name}' already running")

        original_callbacks = self._output_callbacks[:]

        def _recording_wrapper(data: bytes):
            if self.recorder:
                self.recorder.record_output(data)

        if _recording_wrapper not in original_callbacks:
            self._pty_session._output_callbacks.append(_recording_wrapper)

        self._pty_session.start()
        logger.info(f"Session '{self.name}' started (pid={self.pid})")

    def stop(self, timeout: float = 3.0):
        """Stop session gracefully."""
        self._pty_session.stop(timeout=timeout)
        if self.recorder:
            self.recorder.close()
        logger.info(f"Session '{self.name}' stopped")

    def kill(self):
        """Force kill session."""
        self._pty_session.kill()
        if self.recorder:
            self.recorder.close()
        logger.info(f"Session '{self.name}' killed")

    def is_alive(self) -> bool:
        """Check if process is still running."""
        return self._pty_session.is_alive()

    def send_input(self, data: bytes):
        """Send raw bytes to process stdin."""
        if not self._running:
            return
        if self.recorder:
            self.recorder.record_input(data)
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
            "log": str(self.recorder.log_path) if self.recorder else None,
            "buffer_bytes": len(self.get_buffer()),
        }

    def __repr__(self):
        status = "alive" if self.is_alive() else "dead"
        attached = " [attached]" if self._attached else ""
        return f"<ClaudeSession name={self.name!r} pid={self.pid} {status}{attached}>"


__all__ = ["ClaudeSession", "IORecorder"]
