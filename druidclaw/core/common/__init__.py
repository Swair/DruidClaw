"""
Common utilities and interfaces for DruidClaw core modules.
"""
from typing import Protocol, Optional, Callable


class SessionInterface(Protocol):
    """Common interface for all session types."""

    name: str
    pid: Optional[int]
    _running: bool

    def start(self) -> None:
        """Start the session."""
        ...

    def stop(self, timeout: float = ...) -> None:
        """Stop the session gracefully."""
        ...

    def kill(self) -> None:
        """Force kill the session."""
        ...

    def is_alive(self) -> bool:
        """Check if session is still running."""
        ...

    def send_input(self, data: bytes) -> None:
        """Send raw bytes to session stdin."""
        ...

    def send_text(self, text: str) -> None:
        """Send text string as input."""
        ...

    def send_line(self, line: str) -> None:
        """Send a line of text followed by Enter."""
        ...

    def resize(self, rows: int, cols: int) -> None:
        """Resize terminal."""
        ...

    def get_buffer(self) -> bytes:
        """Get current output buffer."""
        ...

    def info(self) -> dict:
        """Get session information."""
        ...


__all__ = [
    "SessionInterface",
]
