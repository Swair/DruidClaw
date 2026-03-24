"""
SSH remote terminal session management.

Provides SSH-based remote terminal functionality using Paramiko.
"""
import os
import threading
import logging
from datetime import datetime
from typing import Optional, Callable


logger = logging.getLogger(__name__)

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False


class SshSession:
    """
    Manages an SSH remote terminal session.

    Uses Paramiko to connect to remote SSH servers.
    """

    def __init__(
        self,
        name: str,
        hostname: str,
        port: int = 22,
        username: str = None,
        password: str = None,
        pkey: str = None,
        workdir: str = ".",
    ):
        if not PARAMIKO_AVAILABLE:
            raise ImportError("paramiko is required for SSH support")

        self.name = name
        self.hostname = hostname
        self.port = port
        self.username = username or os.environ.get("USER")
        self.password = password
        self.pkey = pkey
        self.workdir = workdir
        self.created_at = datetime.now()

        self._attached = False
        self._attach_lock = threading.Lock()

        self._client: Optional[paramiko.SSHClient] = None
        self._channel = None
        self._running = False

        self._buf: bytearray = bytearray()
        self._buf_max = 64 * 1024
        self._buf_lock = threading.Lock()

        self._output_callbacks: list[Callable[[bytes], None]] = []
        self._reader_thread: Optional[threading.Thread] = None

    @property
    def pid(self) -> Optional[int]:
        """SSH session doesn't have a local PID."""
        return None

    def start(self):
        """Start SSH session."""
        if self._running:
            raise RuntimeError(f"Session '{self.name}' already running")

        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        self._client.connect(
            hostname=self.hostname,
            port=self.port,
            username=self.username,
            password=self.password,
            pkey=self.pkey,
        )

        self._channel = self._client.invoke_shell()
        self._channel.setblocking(0)

        if self.workdir:
            self._channel.send(f"cd {self.workdir}\n")

        self._running = True

        logger.info(f"SSH session '{self.name}' started ({self.hostname}:{self.port})")

        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name=f"reader-{self.name}"
        )
        self._reader_thread.start()

    def stop(self, timeout: float = 3.0):
        """Stop SSH session gracefully."""
        if not self._running:
            return
        self._running = False
        if self._channel:
            self._channel.close()
        if self._client:
            self._client.close()
        if self._reader_thread:
            self._reader_thread.join(timeout=timeout)
        logger.info(f"SSH session '{self.name}' stopped")

    def kill(self):
        """Force close SSH session."""
        self._running = False
        if self._channel:
            self._channel.close()
        if self._client:
            self._client.close()
        logger.info(f"SSH session '{self.name}' killed")

    def is_alive(self) -> bool:
        """Check if SSH session is still connected."""
        if not self._running:
            return False
        if self._channel:
            return not self._channel.closed
        return False

    def send_input(self, data: bytes):
        """Send raw bytes to SSH channel."""
        if not self._running or not self._channel:
            return
        try:
            self._channel.send(data)
        except Exception as e:
            logger.warning(f"Failed to send to SSH channel: {e}")

    def send_text(self, text: str):
        """Send text string as input."""
        self.send_input(text.encode())

    def send_line(self, line: str):
        """Send line with Enter."""
        self.send_input((line + "\n").encode())

    def resize(self, rows: int, cols: int):
        """Resize SSH terminal."""
        if self._channel:
            try:
                self._channel.resize_pty(width=cols, height=rows)
            except Exception:
                pass

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
        """Background thread: read SSH channel output and dispatch."""
        import select

        while self._running:
            if not self._channel:
                break

            try:
                if self._channel.recv_ready():
                    data = self._channel.recv(4096)
                    if not data:
                        break

                    with self._buf_lock:
                        self._buf.extend(data)
                        if len(self._buf) > self._buf_max:
                            self._buf = self._buf[-self._buf_max:]

                    for cb in list(self._output_callbacks):
                        try:
                            cb(data)
                        except Exception:
                            pass
                else:
                    import time
                    time.sleep(0.1)

            except Exception:
                break

        self._running = False
        logger.info(f"SSH session '{self.name}' reader loop exited")

    def info(self) -> dict:
        """Get session information."""
        return {
            "name": self.name,
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "alive": self.is_alive(),
            "attached": self._attached,
            "created_at": self.created_at.isoformat(),
            "buffer_bytes": len(self.get_buffer()),
        }

    def __repr__(self):
        status = "alive" if self.is_alive() else "dead"
        attached = " [attached]" if self._attached else ""
        return f"<SshSession name={self.name!r} {self.hostname}:{self.port} {status}{attached}>"


__all__ = ["SshSession"]
