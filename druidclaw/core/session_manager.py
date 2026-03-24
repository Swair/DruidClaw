"""
Session manager for DruidClaw.

Provides unified session management for all session types:
- ClaudeSession: Claude Code sessions
- LocalSession: Local shell terminals
- SshSession: SSH remote terminals
"""
import logging
from enum import Enum
from typing import Optional, Dict, TypeVar, Generic


logger = logging.getLogger(__name__)


class SessionType(str, Enum):
    """Type of session."""
    CLAUDE = "claude"
    LOCAL = "local"
    SSH = "ssh"


class SessionManager:
    """
    Manages multiple sessions of different types.

    Provides a unified interface for creating, accessing, and managing sessions.
    """

    def __init__(self):
        self._sessions: Dict[str, dict] = {}
        self._lock = __import__("threading").Lock()

    def register(
        self,
        name: str,
        session_type: SessionType,
        session_obj,
    ) -> None:
        """
        Register a session.

        Args:
            name: Session name
            session_type: Type of session
            session_obj: Session instance
        """
        with self._lock:
            self._sessions[name] = {
                "type": session_type,
                "obj": session_obj,
            }
        logger.info(f"Session '{name}' registered as {session_type.value}")

    def get(self, name: str) -> Optional[dict]:
        """
        Get session by name.

        Args:
            name: Session name

        Returns:
            Session info dict or None
        """
        with self._lock:
            return self._sessions.get(name)

    def get_session(self, name: str):
        """
        Get session object by name.

        Args:
            name: Session name

        Returns:
            Session object or None
        """
        info = self.get(name)
        return info["obj"] if info else None

    def remove(self, name: str) -> bool:
        """
        Remove a session.

        Args:
            name: Session name

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if name in self._sessions:
                del self._sessions[name]
                logger.info(f"Session '{name}' removed")
                return True
            return False

    def list_sessions(self) -> list[dict]:
        """
        List all registered sessions.

        Returns:
            List of session info dicts
        """
        with self._lock:
            return [
                {
                    "name": name,
                    "type": info["type"].value,
                    "alive": info["obj"].is_alive() if hasattr(info["obj"], "is_alive") else False,
                }
                for name, info in self._sessions.items()
            ]

    def stop_all(self, timeout: float = 3.0) -> None:
        """
        Stop all sessions gracefully.

        Args:
            timeout: Timeout for each session stop
        """
        with self._lock:
            for name, info in list(self._sessions.items()):
                try:
                    info["obj"].stop(timeout=timeout)
                except Exception as e:
                    logger.error(f"Error stopping session '{name}': {e}")

    def kill_all(self) -> None:
        """Force kill all sessions."""
        with self._lock:
            for name, info in list(self._sessions.items()):
                try:
                    info["obj"].kill()
                except Exception as e:
                    logger.error(f"Error killing session '{name}': {e}")


__all__ = ["SessionType", "SessionManager"]
