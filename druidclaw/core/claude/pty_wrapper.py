"""
PTY wrapper for backward compatibility.

This module re-exports PTY utilities from platform.unix for backward compatibility.
For new code, use the platform module directly:
    from druidclaw.core.platform import create_session, PtySession
    from druidclaw.core.platform.unix import create_pty_pair, fork_child, ...

Note: This module only works on Unix/Linux/macOS.
      On Windows, use ConPtySession from druidclaw.core.platform.windows.
"""
import os

# Platform detection
IS_WINDOWS = os.name == "nt"

# For backward compatibility, export PTYSession from the platform layer
if not IS_WINDOWS:
    # Unix/Linux/macOS: always has pty support
    from ..platform.unix import (
        PtySession,
        create_pty_pair,
        fork_child,
        get_terminal_size,
        set_pty_size,
        set_terminal_raw_mode,
        restore_terminal_mode,
    )
else:
    # Windows: try to import ConPtySession
    try:
        from ..platform.windows import ConPtySession as PtySession
    except ImportError:
        # pywinpty not available
        class _UnavailableSession:
            """Placeholder class when pywinpty is not available."""
            def __init__(self, *args, **kwargs):
                raise ImportError(
                    "pywinpty is required on Windows for PTY sessions. "
                    "Install with: pip install pywinpty"
                )
        PtySession = _UnavailableSession

        # Placeholder functions for Windows
        def create_pty_pair():
            raise ImportError("PTY not available on Windows without pywinpty")

        def fork_child(*args, **kwargs):
            raise ImportError("PTY not available on Windows without pywinpty")

        def get_terminal_size(*args, **kwargs):
            raise ImportError("PTY not available on Windows without pywinpty")

        def set_pty_size(*args, **kwargs):
            raise ImportError("PTY not available on Windows without pywinpty")

        def set_terminal_raw_mode(*args, **kwargs):
            raise ImportError("PTY not available on Windows without pywinpty")

        def restore_terminal_mode(*args, **kwargs):
            raise ImportError("PTY not available on Windows without pywinpty")

# Re-export IORecorder from claude module for backward compatibility
from ..claude import IORecorder

__all__ = [
    "PtySession",
    "IORecorder",
    "IS_WINDOWS",
    # Low-level utilities
    "create_pty_pair",
    "fork_child",
    "get_terminal_size",
    "set_pty_size",
    "set_terminal_raw_mode",
    "restore_terminal_mode",
]
