"""
PTY-based Claude Code session management.

Compatibility layer - imports from claude module.
For new code, use: from druidclaw.core.claude import ClaudeSession
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

# Re-export from claude module for backward compatibility
from .claude import ClaudeSession, IORecorder

logger = logging.getLogger(__name__)

# Default claude executable
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
LOG_DIR = Path(os.environ.get("DRUIDCLAW_LOG_DIR",
               str(Path(__file__).resolve().parent.parent.parent / "log")))


__all__ = ["ClaudeSession", "IORecorder"]
