"""
Windows ConPTY-based terminal session implementation.

Uses pywinpty for pseudo-terminal emulation on Windows.
Requires: pip install pywinpty

Note: Windows ConPTY is available on Windows 10+ and Windows Server 2019+
"""
import os
import sys
import threading
import logging
import time
from typing import Optional, Callable, List, Dict, Any

logger = logging.getLogger(__name__)

__all__ = ["ConPtySession"]

# pywinpty import (optional, will be imported at runtime)
winpty = None
PTY = None


class ConPtySession:
    """
    Windows ConPTY-based terminal session.

    Uses pywinpty to create a pseudo-terminal on Windows.
    This provides similar functionality to Unix PTY sessions.
    """

    def __init__(
        self,
        name: str,
        cmd: List[str] = None,
        workdir: str = ".",
        env: Optional[Dict[str, str]] = None,
        rows: int = 24,
        cols: int = 80,
    ):
        """
        Initialize a ConPTY session.

        Args:
            name: Session identifier
            cmd: Command and arguments to execute (default: cmd.exe)
            workdir: Working directory for the process
            env: Environment variables (merged with system env)
            rows: Initial terminal rows
            cols: Initial terminal columns
        """
        global winpty

        # Default to cmd.exe on Windows
        if cmd is None:
            cmd = ["cmd.exe"]

        # Wrap command with cmd.exe /c for proper PATH resolution
        # This ensures commands like 'claude' are found in PATH
        cmd_str = " ".join(cmd)
        if cmd_str != "cmd.exe":
            cmd = ["cmd.exe", "/c", cmd_str]

        # Import winpty lazily
        if winpty is None:
            try:
                import winpty
                from winpty import PTY as PTYClass
                # Update module-level variables
                globals()['winpty'] = winpty
                globals()['PTY'] = PTYClass
            except ImportError as e:
                raise ImportError(
                    "Windows requires 'pywinpty' for terminal sessions. "
                    "Install with: pip install pywinpty"
                ) from e

        self.name = name
        self.cmd = cmd
        self.workdir = os.path.abspath(workdir)
        self.env = env or {}
        self._term_size = (rows, cols)

        self._running = False
        self._pid: Optional[int] = None
        self._pty: Optional[Any] = None
        self._buf: bytearray = bytearray()
        self._buf_max = 64 * 1024
        self._buf_lock = threading.Lock()
        self._output_callbacks: List[Callable[[bytes], None]] = []
        self._reader_thread: Optional[threading.Thread] = None

    @property
    def pid(self) -> Optional[int]:
        """Get process ID."""
        return self._pid

    @property
    def running(self) -> bool:
        """Check if session is running."""
        return self._running

    @property
    def term_size(self) -> tuple:
        """Get terminal size (rows, cols)."""
        return self._term_size

    def start(self) -> None:
        """Start the ConPTY session."""
        if self._running:
            raise RuntimeError(f"Session '{self.name}' already running")
        self._start_impl()
        # _running is set to True in _start_impl() after pty is fully initialized

    def _start_impl(self) -> None:
        """Start the ConPTY session."""
        # Build environment string
        env_dict = os.environ.copy()
        env_dict.update(self.env)
        env_dict["TERM"] = "xterm-256color"

        # Convert command list to string
        cmd_str = " ".join(self.cmd)

        try:
            # Create PTY with specified dimensions (new pywinpty API)
            self._pty = PTY(
                cols=self._term_size[1],
                rows=self._term_size[0],
            )

            # Spawn the process
            self._pty.spawn(cmd_str)

            self._pid = self._pty.pid

            logger.info(f"ConPtySession started (pid={self._pid})")

            # Set _running to True before starting reader thread
            # This ensures the reader loop can execute
            self._running = True

            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._reader_loop, daemon=True, name=f"reader-{self.name}"
            )
            self._reader_thread.start()

        except Exception as e:
            logger.error(f"Failed to start ConPtySession: {e}")
            raise RuntimeError(f"Failed to start session: {e}") from e

    def stop(self, timeout: float = 3.0) -> None:
        """Stop session gracefully."""
        if not self._running:
            return
        self._stop_impl(timeout)
        self._running = False

    def _stop_impl(self, timeout: float) -> None:
        """Stop session gracefully."""
        if self._pty is None:
            return

        try:
            # Send Ctrl+C to gracefully terminate
            self._pty.write("\x03")
        except Exception:
            pass

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=timeout)

        self._close_agent()
        self._output_callbacks.clear()
        logger.info("ConPtySession stopped")

    def kill(self) -> None:
        """Force kill the session."""
        if not self._running:
            return
        self._kill_impl()
        self._running = False

    def _kill_impl(self) -> None:
        """Force kill the session."""
        if self._pty is None:
            return

        try:
            # Send Ctrl+Break for force kill
            self._pty.write("\x1a")
        except Exception:
            pass

        self._close_agent()
        self._output_callbacks.clear()

        # Wait briefly for reader thread to exit
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.5)

        logger.info("ConPtySession killed")

    def _close_agent(self) -> None:
        """Close the winpty agent."""
        if self._pty is not None:
            try:
                # New pywinpty API doesn't have close(), just clear reference
                pass
            except Exception:
                pass
            self._pty = None

    def is_alive(self) -> bool:
        """Check if the session is still alive."""
        if not self._running or self._pty is None:
            return False

        try:
            return self._pty.isalive()
        except Exception:
            return False

    def send_input(self, data: bytes) -> None:
        """Send data to the PTY."""
        if not self._running or self._pty is None:
            return

        try:
            # Decode bytes to string for winpty
            text = data.decode("utf-8", errors="replace")
            self._pty.write(text)
        except Exception as e:
            logger.warning(f"Failed to write to ConPTY: {e}")

    def send_text(self, text: str) -> None:
        """Send text string as input."""
        self.send_input(text.encode("utf-8"))

    def send_line(self, line: str) -> None:
        """Send line with Enter."""
        self.send_input((line + "\n").encode("utf-8"))

    def resize(self, rows: int, cols: int) -> None:
        """Resize the terminal."""
        self._term_size = (rows, cols)
        self._resize_impl(rows, cols)

    def _resize_impl(self, rows: int, cols: int) -> None:
        """Resize the terminal."""
        if self._pty is None:
            return

        try:
            # pywinpty set_size takes (cols, rows) order - opposite of Unix!
            self._pty.set_size(cols, rows)
        except Exception as e:
            logger.warning(f"Failed to resize ConPTY: {e}")

    def get_buffer(self) -> bytes:
        """Get current output buffer."""
        with self._buf_lock:
            return bytes(self._buf)

    def add_output_callback(self, cb: Callable[[bytes], None]) -> None:
        """Register output callback."""
        self._output_callbacks.append(cb)

    def remove_output_callback(self, cb: Callable[[bytes], None]) -> None:
        """Remove output callback."""
        try:
            self._output_callbacks.remove(cb)
        except ValueError:
            pass

    def info(self) -> Dict[str, Any]:
        """Get session information."""
        return {
            "name": self.name,
            "pid": self.pid,
            "workdir": self.workdir,
            "alive": self.is_alive(),
            "running": self._running,
            "term_size": self._term_size,
            "buffer_bytes": len(self.get_buffer()),
        }

    def __repr__(self) -> str:
        status = "alive" if self.is_alive() else "dead"
        return f"<{self.__class__.__name__} name={self.name!r} pid={self.pid} {status}>"

    # ------------------------------------------------------------------ #
    #  Reader loop                                                        #
    # ------------------------------------------------------------------ #

    def _reader_loop(self) -> None:
        """Background thread: read ConPTY output and dispatch to callbacks."""
        while self._running and self._pty is not None:
            try:
                # Read from PTY
                data = self._pty.read()

                if data:
                    # Update buffer
                    with self._buf_lock:
                        self._buf.extend(data.encode("utf-8"))
                        if len(self._buf) > self._buf_max:
                            self._buf = self._buf[-self._buf_max:]

                    # Dispatch to callbacks
                    for cb in list(self._output_callbacks):
                        try:
                            cb(data.encode("utf-8"))
                        except Exception:
                            pass

                # Small sleep to avoid busy-waiting
                time.sleep(0.01)

            except Exception as e:
                logger.debug(f"Reader loop error: {e}")
                if not self.is_alive():
                    break
                time.sleep(0.1)

        self._running = False
        logger.info("ConPtySession reader loop exited")
