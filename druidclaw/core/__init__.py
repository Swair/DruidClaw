"""
Core session management for DruidClaw.

Provides unified session management for:
- Claude Code sessions
- Local shell terminals
- SSH remote terminals
"""
from .claude import ClaudeSession, IORecorder
from .local import LocalSession
from .ssh import SshSession
from .session_manager import SessionManager, SessionType
from .daemon import CCDaemon, run_daemon, is_daemon_running, SOCKET_PATH, RUN_DIR, PID_FILE
from .client import DaemonClient, attach_to_session
from .io_recorder import IORecorder as IORecorderBase
from .claude.pty_utils import (
    get_terminal_size,
    set_pty_size,
    set_terminal_raw_mode,
    restore_terminal_mode,
    create_pty_pair,
    fork_child,
)


__all__ = [
    # Session types
    "ClaudeSession",
    "LocalSession",
    "SshSession",
    # Session management
    "SessionManager",
    "SessionType",
    # I/O recording
    "IORecorder",
    "IORecorderBase",
    # PTY utilities
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
