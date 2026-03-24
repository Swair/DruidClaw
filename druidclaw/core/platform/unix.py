"""
Unix/Linux PTY-based terminal session implementation.

Uses pseudo-terminal (PTY) for interactive terminal emulation on POSIX systems.

For cross-platform code, use:
    from druidclaw.core.platform import create_session, PtySession

For low-level PTY operations (Unix only):
    from druidclaw.core.platform.unix import (
        create_pty_pair,
        fork_child,
        get_terminal_size,
        set_pty_size,
        set_terminal_raw_mode,
        restore_terminal_mode,
    )
"""
import os
import pty
import fcntl
import termios
import struct
import signal
import select
import threading
import logging
from typing import Optional, Callable, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "PtySession",
    "create_pty_pair",
    "fork_child",
    "get_terminal_size",
    "set_pty_size",
    "set_terminal_raw_mode",
    "restore_terminal_mode",
]


class PtySession:
    """
    Unix PTY-based terminal session.

    Uses os.fork() and pty.openpty() to create a pseudo-terminal
    pair for interactive terminal sessions.
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
        Initialize a PTY session.

        Args:
            name: Session identifier
            cmd: Command and arguments to execute (default: /bin/bash)
            workdir: Working directory for the process
            env: Environment variables (merged with system env)
            rows: Initial terminal rows
            cols: Initial terminal columns
        """
        # Default to bash shell
        if cmd is None:
            shell = os.environ.get("SHELL", "/bin/bash")
            cmd = [shell]

        self.name = name
        self.cmd = cmd
        self.workdir = os.path.abspath(workdir)
        self.env = env or {}
        self._term_size = (rows, cols)

        self._running = False
        self._pid: Optional[int] = None
        self.master_fd: Optional[int] = None
        self._child_pid: Optional[int] = None
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
        """Start the PTY session."""
        if self._running:
            raise RuntimeError(f"Session '{self.name}' already running")
        self._running = True
        self._start_impl()

    def _start_impl(self) -> None:
        """Start the PTY session."""
        env = os.environ.copy()
        env.update(self.env)
        env["TERM"] = "xterm-256color"

        # Create PTY pair
        master_fd, slave_fd = create_pty_pair()
        set_pty_size(master_fd, *self._term_size)

        # Fork child process
        child_pid = fork_child(master_fd, slave_fd, self.workdir, self.cmd, env)

        # Parent: close slave, store master
        os.close(slave_fd)
        self._pid = child_pid
        self._child_pid = child_pid
        self.master_fd = master_fd

        logger.info(f"PTYSession started (pid={self._pid})")

        # Start reader thread
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name=f"reader-{self._pid}"
        )
        self._reader_thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Stop session gracefully with SIGTERM."""
        if not self._running:
            return
        if self._pid is None:
            return
        try:
            os.kill(self._pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=timeout)

        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass

        self._running = False
        self._output_callbacks.clear()
        logger.info("PTYSession stopped")

    def kill(self) -> None:
        """Force kill with SIGKILL."""
        if not self._running:
            return
        if self._pid is None:
            return
        try:
            os.kill(self._pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        # Close master_fd to unblock select() in reader thread
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
        self.master_fd = None

        self._running = False
        self._output_callbacks.clear()

        # Wait briefly for reader thread to exit
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.5)

        logger.info("PTYSession killed")

    def is_alive(self) -> bool:
        """Check if child process is still running."""
        if not self._running or self._pid is None:
            return False
        try:
            result = os.waitpid(self._pid, os.WNOHANG)
            if result[0] != 0:
                self._running = False
                return False
            return True
        except ChildProcessError:
            self._running = False
            return False

    def send_input(self, data: bytes) -> None:
        """Send data to PTY master (child stdin)."""
        if not self._running or self.master_fd is None:
            return
        try:
            os.write(self.master_fd, data)
        except OSError as e:
            logger.warning(f"Failed to write to PTY: {e}")

    def send_text(self, text: str) -> None:
        """Send text string as input."""
        self.send_input(text.encode("utf-8"))

    def send_line(self, line: str) -> None:
        """Send line with Enter."""
        self.send_input((line + "\n").encode("utf-8"))

    def resize(self, rows: int, cols: int) -> None:
        """Update PTY window size."""
        self._term_size = (rows, cols)
        if self.master_fd is not None:
            set_pty_size(self.master_fd, rows, cols)

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

    def _fork_child(self, master_fd: int, slave_fd: int, cmd: List[str], env: Dict) -> int:
        """Fork child process with PTY - compatibility wrapper."""
        return fork_child(master_fd, slave_fd, self.workdir, cmd, env)

    # ------------------------------------------------------------------ #
    #  Reader loop                                                        #
    # ------------------------------------------------------------------ #

    def _reader_loop(self) -> None:
        """Background thread: read PTY output and dispatch to callbacks."""
        while self._running:
            # Check if master_fd is still valid
            if self.master_fd is None:
                break

            try:
                r, _, _ = select.select([self.master_fd], [], [], 0.5)
            except (ValueError, select.error, OSError):
                break

            if not r:
                if not self.is_alive():
                    break
                continue

            # Re-check master_fd after select() returns
            if self.master_fd is None:
                break

            try:
                data = os.read(self.master_fd, 4096)
            except OSError:
                break

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

        # Cleanup: wait for child process to avoid zombies
        if self._pid:
            try:
                os.waitpid(self._pid, 0)
            except ChildProcessError:
                pass

        self._running = False
        logger.info("PTYSession reader loop exited")


# -----------------------------------------------------------------------------
# Low-level PTY utilities (public API for advanced usage)
# -----------------------------------------------------------------------------

def create_pty_pair() -> Tuple[int, int]:
    """
    Create a PTY master/slave pair.

    Returns:
        Tuple of (master_fd, slave_fd)
    """
    return pty.openpty()


def get_terminal_size(fd: int) -> Tuple[int, int]:
    """
    Get terminal window size.

    Args:
        fd: File descriptor of terminal

    Returns:
        Tuple of (rows, cols), minimum (24, 80)
    """
    size = struct.pack("HHHH", 0, 0, 0, 0)
    size = fcntl.ioctl(fd, termios.TIOCGWINSZ, size)
    rows, cols, _, _ = struct.unpack("HHHH", size)
    return max(rows, 24), max(cols, 80)


def set_pty_size(fd: int, rows: int, cols: int) -> None:
    """
    Set PTY window size.

    Args:
        fd: PTY file descriptor
        rows: Number of rows
        cols: Number of columns
    """
    size = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, size)


def set_terminal_raw_mode(fd: int) -> list:
    """
    Put terminal fd into raw mode.

    Args:
        fd: File descriptor of terminal

    Returns:
        Original terminal attributes for restoration
    """
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
    return attrs


def restore_terminal_mode(fd: int, attrs: list) -> None:
    """
    Restore terminal to original mode.

    Args:
        fd: File descriptor of terminal
        attrs: Original terminal attributes
    """
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except termios.error:
        pass


def fork_child(
    master_fd: int,
    slave_fd: int,
    workdir: str,
    cmd: list,
    env: dict,
) -> int:
    """
    Fork child process with PTY.

    Args:
        master_fd: PTY master file descriptor
        slave_fd: PTY slave file descriptor
        workdir: Working directory for child
        cmd: Command to execute
        env: Environment variables

    Returns:
        Child PID in parent, 0 in child (never returns in child)
    """
    pid = os.fork()
    if pid == 0:
        # Child process
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.chdir(workdir)
        os.execvpe(cmd[0], cmd, env)
        os._exit(1)
    return pid
