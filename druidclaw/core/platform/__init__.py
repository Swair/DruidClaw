"""
Cross-platform terminal session abstraction layer.

This module provides a unified interface for terminal sessions across
different operating systems:
- Unix/Linux/macOS: PtySession (using pty)
- Windows: ConPtySession (using winpty)

Usage:
    from druidclaw.core.platform import create_session

    session = create_session(
        name="my-session",
        cmd=["bash"],
        workdir="/tmp",
    )
    session.start()
    session.send_line("ls -la")
    buffer = session.get_buffer()
"""
import os
import sys
from typing import Optional, Callable, List, Dict, Any

# Platform detection
IS_WINDOWS = os.name == "nt"

__all__ = [
    "BaseSession",
    "PtySession",
    "ConPtySession",
    "create_session",
    "get_platform_session_class",
    "IS_WINDOWS",
    # Low-level utilities (Unix only)
    "create_pty_pair",
    "fork_child",
    "get_terminal_size",
    "set_pty_size",
    "set_terminal_raw_mode",
    "restore_terminal_mode",
]

# Import platform-specific implementations
# Note: Import directly from submodules to avoid circular imports
if IS_WINDOWS:
    from .windows import ConPtySession
    PtySession = None
    # Low-level utilities not available on Windows
    create_pty_pair = None
    fork_child = None
    get_terminal_size = None
    set_pty_size = None
    set_terminal_raw_mode = None
    restore_terminal_mode = None
else:
    from .unix import (
        PtySession,
        create_pty_pair,
        fork_child,
        get_terminal_size,
        set_pty_size,
        set_terminal_raw_mode,
        restore_terminal_mode,
    )
    ConPtySession = None


class BaseSession:
    """
    Abstract base class for terminal sessions.

    Provides a unified interface for:
    - Starting/stopping terminal processes
    - Sending input (raw bytes, text, lines)
    - Reading output buffer
    - Resizing terminal
    - Lifecycle management

    Note: This is a protocol/base class definition. For actual usage,
    use PtySession (Unix) or ConPtySession (Windows) directly, or
    use the create_session() factory function.
    """

    def __init__(
        self,
        name: str,
        cmd: List[str],
        workdir: str = ".",
        env: Optional[Dict[str, str]] = None,
        rows: int = 24,
        cols: int = 80,
    ):
        """
        Initialize a terminal session.

        Args:
            name: Session identifier
            cmd: Command and arguments to execute
            workdir: Working directory for the process
            env: Environment variables (merged with system env)
            rows: Initial terminal rows
            cols: Initial terminal columns
        """
        self.name = name
        self.cmd = cmd
        self.workdir = os.path.abspath(workdir)
        self.env = env or {}
        self._term_size = (rows, cols)

        self._running = False
        self._pid: Optional[int] = None

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
        """Start the session."""
        raise NotImplementedError

    def stop(self, timeout: float = 3.0) -> None:
        """Stop the session."""
        raise NotImplementedError

    def kill(self) -> None:
        """Force kill the session."""
        raise NotImplementedError

    def is_alive(self) -> bool:
        """Check if session is alive."""
        raise NotImplementedError

    def send_input(self, data: bytes) -> None:
        """Send raw bytes to session stdin."""
        raise NotImplementedError

    def send_text(self, text: str) -> None:
        """Send text string as input."""
        self.send_input(text.encode("utf-8"))

    def send_line(self, line: str) -> None:
        """Send line with Enter."""
        self.send_input((line + "\n").encode("utf-8"))

    def resize(self, rows: int, cols: int) -> None:
        """Resize terminal."""
        raise NotImplementedError

    def get_buffer(self) -> bytes:
        """Get current output buffer."""
        raise NotImplementedError

    def info(self) -> Dict[str, Any]:
        """Get session information."""
        return {
            "name": self.name,
            "pid": self.pid,
            "workdir": self.workdir,
            "alive": self.is_alive(),
            "running": self._running,
            "term_size": self._term_size,
        }


def get_platform_session_class():
    """
    Get the appropriate session class for the current platform.

    Returns:
        The session class (PtySession or ConPtySession)

    Raises:
        ImportError: If no suitable session implementation is available
    """
    if IS_WINDOWS:
        try:
            from .windows import ConPtySession
            return ConPtySession
        except ImportError as e:
            raise ImportError(
                "Windows requires 'pywinpty' for terminal sessions. "
                "Install with: pip install pywinpty"
            ) from e
    else:
        from .unix import PtySession
        return PtySession


def create_session(
    name: str,
    cmd: List[str] = None,
    workdir: str = ".",
    env: Optional[Dict[str, str]] = None,
    rows: int = 24,
    cols: int = 80,
    **kwargs,
) -> Any:
    """
    Create a platform-appropriate terminal session.

    Args:
        name: Session identifier
        cmd: Command and arguments to execute
        workdir: Working directory for the process
        env: Environment variables (merged with system env)
        rows: Initial terminal rows
        cols: Initial terminal columns
        **kwargs: Platform-specific arguments

    Returns:
        A platform-appropriate session instance (PtySession or ConPtySession)

    Raises:
        ImportError: If required platform-specific dependencies are missing
    """
    session_class = get_platform_session_class()
    return session_class(
        name=name,
        cmd=cmd,
        workdir=workdir,
        env=env,
        rows=rows,
        cols=cols,
        **kwargs,
    )
