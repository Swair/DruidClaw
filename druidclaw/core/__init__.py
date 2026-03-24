"""
Core session management for DruidClaw.

Provides unified session management for:
- Claude Code sessions
- Local shell terminals
- SSH remote terminals

Cross-platform support:
- Unix/Linux/macOS: Full PTY support
- Windows: Requires pywinpty for local/Claude sessions
"""
from .claude import ClaudeSession, IORecorder
from .local import LocalSession
from .ssh import SshSession
from .session_manager import SessionManager, SessionType
from .daemon import CCDaemon, run_daemon, is_daemon_running, SOCKET_PATH, RUN_DIR, PID_FILE
from .client import DaemonClient, attach_to_session
from .io_recorder import IORecorder as IORecorderBase

# Cross-platform platform layer (new)
from .platform import (
    BaseSession,
    PtySession,
    ConPtySession,
    create_session,
    get_platform_session_class,
    IS_WINDOWS,
)

# PTY utilities (Unix only, for backward compatibility)
# On Windows, these will raise ImportError if pywinpty is not available
if not IS_WINDOWS:
    from .platform import (
        get_terminal_size,
        set_pty_size,
        set_terminal_raw_mode,
        restore_terminal_mode,
        create_pty_pair,
        fork_child,
    )
else:
    # Placeholders for Windows
    get_terminal_size = None
    set_pty_size = None
    set_terminal_raw_mode = None
    restore_terminal_mode = None
    create_pty_pair = None
    fork_child = None


__all__ = [
    # Session types
    "ClaudeSession",
    "LocalSession",
    "SshSession",
    # Cross-platform base class
    "BaseSession",
    "PtySession",      # Unix: real impl, Windows: None
    "ConPtySession",   # Windows: real impl, Unix: None
    "create_session",  # Cross-platform factory
    "get_platform_session_class",
    "IS_WINDOWS",
    # Session management
    "SessionManager",
    "SessionType",
    # I/O recording
    "IORecorder",
    "IORecorderBase",
    # PTY utilities (Unix only)
    "get_terminal_size",
    "set_pty_size",
    "set_terminal_raw_mode",
    "restore_terminal_mode",
    "create_pty_pair",
    "fork_child",
    # Daemon
    "CCDaemon",
    "run_daemon",
    "is_daemon_running",
    "SOCKET_PATH",
    "RUN_DIR",
    "PID_FILE",
    # Client
    "DaemonClient",
    "attach_to_session",
]
