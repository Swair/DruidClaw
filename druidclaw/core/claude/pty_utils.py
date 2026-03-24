"""
PTY (Pseudo-Terminal) utilities for Unix systems.

Provides low-level PTY operations for session management.
"""
import os
import pty
import fcntl
import termios
import struct
from typing import Tuple


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


def create_pty_pair() -> Tuple[int, int]:
    """
    Create a PTY master/slave pair.

    Returns:
        Tuple of (master_fd, slave_fd)
    """
    return pty.openpty()


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


__all__ = [
    "get_terminal_size",
    "set_pty_size",
    "set_terminal_raw_mode",
    "restore_terminal_mode",
    "create_pty_pair",
    "fork_child",
]
