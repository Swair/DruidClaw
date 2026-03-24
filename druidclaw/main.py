"""
cc - Claude Code Manager CLI
Usage:
  cc start [<name>] [-d <dir>] [-- <claude-args>...]   Start a new session
  cc attach <name>                                       Attach to a session
  cc new [<name>] [-d <dir>]                            Create session (no attach)
  cc ls                                                  List sessions
  cc info <name>                                         Show session details
  cc kill <name> [-f]                                    Kill a session
  cc send <name> <text>                                  Send text to session
  cc sendline <name> <line>                              Send line (+ Enter)
  cc buf <name>                                          Print session output buffer
  cc log <name>                                          Tail the session log
  cc daemon start [--fg]                                 Start daemon
  cc daemon stop                                         Stop daemon
  cc daemon status                                       Daemon status
  cc run [-- <claude-args>...]                           Run claude directly (no daemon)
"""
import os
import sys
import json
import signal
import time
import subprocess
import argparse
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from druidclaw.core.daemon import (
    run_daemon, is_daemon_running,
    SOCKET_PATH, RUN_DIR, PID_FILE
)
from druidclaw.core.client import DaemonClient, attach_to_session


def ensure_daemon():
    """Start daemon if not running."""
    if not is_daemon_running():
        print("[cc] Starting daemon...", flush=True)
        _start_daemon(foreground=False)
        # Wait for it to come up
        for _ in range(20):
            time.sleep(0.2)
            if is_daemon_running():
                break
        else:
            print("[cc] ERROR: daemon failed to start", file=sys.stderr)
            sys.exit(1)


def _start_daemon(foreground: bool = False):
    if foreground:
        run_daemon(foreground=True)
    else:
        import subprocess
        subprocess.Popen(
            [sys.executable, "-m", "druidclaw.core.daemon_main"],
            close_fds=True,
            start_new_session=True,
        )


# ------------------------------------------------------------------ #
#  Commands                                                           #
# ------------------------------------------------------------------ #

def cmd_start(args):
    """Start a new session and attach to it."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.new_session(
            name=args.name,
            workdir=args.workdir or os.getcwd(),
            args=args.claude_args or [],
        )
        if "error" in r:
            print(f"[cc] Error: {r['error']}", file=sys.stderr)
            sys.exit(1)
        name = r["name"]
        print(f"[cc] Session '{name}' started (pid={r['pid']})")

    # Attach
    print(f"[cc] Attaching (Ctrl-Z to detach, Ctrl-C to exit claude)...")
    attach_to_session(name, None)


def cmd_new(args):
    """Create a session without attaching."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.new_session(
            name=args.name,
            workdir=args.workdir or os.getcwd(),
            args=args.claude_args or [],
        )
        if "error" in r:
            print(f"[cc] Error: {r['error']}", file=sys.stderr)
            sys.exit(1)
        print(f"[cc] Session '{r['name']}' created (pid={r['pid']})")


def cmd_attach(args):
    """Attach to an existing session."""
    ensure_daemon()
    attach_to_session(args.name, None)


def cmd_ls(args):
    """List all sessions."""
    ensure_daemon()
    with DaemonClient() as c:
        sessions = c.list_sessions()

    if not sessions:
        print("[cc] No active sessions")
        return

    # Table output
    header = f"{'NAME':<20} {'PID':>7}  {'ALIVE':<6}  {'ATTACHED':<8}  {'CREATED':<20}  {'LOG'}"
    print(header)
    print("-" * len(header))
    for s in sessions:
        alive = "yes" if s.get("alive") else "no"
        attached = "yes" if s.get("attached") else "no"
        created = s.get("created_at", "")[:19].replace("T", " ")
        log = s.get("log", "")
        log_short = ("..." + log[-37:]) if log and len(log) > 40 else (log or "")
        print(
            f"{s['name']:<20} {s.get('pid', 0):>7}  {alive:<6}  {attached:<8}  {created:<20}  {log_short}"
        )


def cmd_info(args):
    """Show detailed session info."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.session_info(args.name)
    if "error" in r:
        print(f"[cc] Error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    s = r["session"]
    for k, v in s.items():
        print(f"  {k:<16}: {v}")


def cmd_kill(args):
    """Kill a session."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.kill_session(args.name, force=args.force)
    if "error" in r:
        print(f"[cc] Error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    print(f"[cc] Session '{args.name}' killed")


def cmd_send(args):
    """Send text to a session (non-interactive)."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.send_input(args.name, text=args.text)
    if "error" in r:
        print(f"[cc] Error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    print("[cc] Sent")


def cmd_sendline(args):
    """Send a line (with Enter) to a session."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.send_input(args.name, line=args.line)
    if "error" in r:
        print(f"[cc] Error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    print("[cc] Sent")


def cmd_buf(args):
    """Print the buffered output of a detached session."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.get_buffer(args.name)
    if "error" in r:
        print(f"[cc] Error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    text = r.get("text", "")
    print(text, end="")
    print(f"\n[{r['bytes']} bytes buffered]", file=sys.stderr)


def cmd_log(args):
    """Tail the session log file."""
    ensure_daemon()
    with DaemonClient() as c:
        r = c.session_info(args.name)
    if "error" in r:
        print(f"[cc] Error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    log_path = r["session"].get("log")
    if not log_path or not Path(log_path).exists():
        print(f"[cc] No log file found for '{args.name}'", file=sys.stderr)
        sys.exit(1)
    print(f"[cc] Tailing {log_path} (Ctrl-C to stop)")
    try:
        subprocess.run(["tail", "-f", "-n", str(args.lines), log_path])
    except KeyboardInterrupt:
        pass


def cmd_daemon_start(args):
    if is_daemon_running():
        print("[cc] Daemon is already running")
        return
    if args.foreground:
        print("[cc] Starting daemon in foreground...")
        run_daemon(foreground=True)
    else:
        _start_daemon(foreground=False)
        for _ in range(20):
            time.sleep(0.2)
            if is_daemon_running():
                print("[cc] Daemon started")
                return
        print("[cc] ERROR: Daemon did not start in time", file=sys.stderr)
        sys.exit(1)


def cmd_daemon_stop(args):
    if not PID_FILE.exists():
        print("[cc] Daemon not running (no PID file)")
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"[cc] Sent SIGTERM to daemon (pid={pid})")
    except (ValueError, ProcessLookupError):
        print("[cc] Daemon process not found")
        PID_FILE.unlink(missing_ok=True)


def cmd_daemon_status(args):
    running = is_daemon_running()
    status = "running" if running else "stopped"
    pid = ""
    if PID_FILE.exists():
        try:
            pid = f" (pid={PID_FILE.read_text().strip()})"
        except Exception:
            pass
    print(f"[cc] Daemon: {status}{pid}")
    if running:
        with DaemonClient() as c:
            sessions = c.list_sessions()
        print(f"[cc] Active sessions: {len(sessions)}")


def cmd_run(args):
    """
    Run claude directly (no daemon) with I/O recording.
    Useful for simple single-session use.
    """
    from druidclaw.core.claude import ClaudeSession
    name = args.name or f"direct_{os.getpid()}"
    s = ClaudeSession(
        name=name,
        workdir=args.workdir or os.getcwd(),
        claude_args=args.claude_args or [],
        enable_recording=not args.no_record,
    )
    s.start()
    if s.recorder:
        print(f"[cc] Recording to {s.recorder.log_path}", file=sys.stderr)
    print("[cc] Running (Ctrl-Z to stop recording, Ctrl-C to exit claude)", file=sys.stderr)
    try:
        s.attach()
    except KeyboardInterrupt:
        pass
    finally:
        s.stop()


# ------------------------------------------------------------------ #
#  Argument parser                                                    #
# ------------------------------------------------------------------ #

def build_parser():
    p = argparse.ArgumentParser(
        prog="cc",
        description="Claude Code Manager — manage multiple claude sessions",
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")

    # start
    p_start = sub.add_parser("start", help="Start a new session and attach")
    p_start.add_argument("name", nargs="?", default=None, help="Session name")
    p_start.add_argument("-d", "--workdir", default=None, help="Working directory")
    p_start.add_argument("claude_args", nargs=argparse.REMAINDER, help="Args for claude")

    # new
    p_new = sub.add_parser("new", help="Create a session (no attach)")
    p_new.add_argument("name", nargs="?", default=None)
    p_new.add_argument("-d", "--workdir", default=None)
    p_new.add_argument("claude_args", nargs=argparse.REMAINDER)

    # attach
    p_attach = sub.add_parser("attach", help="Attach to an existing session")
    p_attach.add_argument("name", help="Session name")

    # ls
    sub.add_parser("ls", help="List sessions")

    # info
    p_info = sub.add_parser("info", help="Show session details")
    p_info.add_argument("name")

    # kill
    p_kill = sub.add_parser("kill", help="Kill a session")
    p_kill.add_argument("name")
    p_kill.add_argument("-f", "--force", action="store_true")

    # send
    p_send = sub.add_parser("send", help="Send text to a session")
    p_send.add_argument("name")
    p_send.add_argument("text")

    # sendline
    p_sendline = sub.add_parser("sendline", help="Send a line to a session")
    p_sendline.add_argument("name")
    p_sendline.add_argument("line")

    # buf
    p_buf = sub.add_parser("buf", help="Print buffered output")
    p_buf.add_argument("name")

    # log
    p_log = sub.add_parser("log", help="Tail session log")
    p_log.add_argument("name")
    p_log.add_argument("-n", "--lines", type=int, default=50)

    # daemon
    p_daemon = sub.add_parser("daemon", help="Daemon management")
    d_sub = p_daemon.add_subparsers(dest="daemon_cmd", metavar="<daemon-cmd>")
    p_d_start = d_sub.add_parser("start")
    p_d_start.add_argument("--fg", "--foreground", dest="foreground", action="store_true")
    d_sub.add_parser("stop")
    d_sub.add_parser("status")

    # run (direct, no daemon)
    p_run = sub.add_parser("run", help="Run claude directly with I/O recording")
    p_run.add_argument("name", nargs="?", default=None)
    p_run.add_argument("-d", "--workdir", default=None)
    p_run.add_argument("--no-record", action="store_true")
    p_run.add_argument("claude_args", nargs=argparse.REMAINDER)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Strip leading '--' from claude_args remainder
    if hasattr(args, "claude_args") and args.claude_args:
        if args.claude_args[0] == "--":
            args.claude_args = args.claude_args[1:]

    dispatch = {
        "start":    cmd_start,
        "new":      cmd_new,
        "attach":   cmd_attach,
        "ls":       cmd_ls,
        "info":     cmd_info,
        "kill":     cmd_kill,
        "send":     cmd_send,
        "sendline": cmd_sendline,
        "buf":      cmd_buf,
        "log":      cmd_log,
        "run":      cmd_run,
    }

    if args.command == "daemon":
        if args.daemon_cmd == "start":
            cmd_daemon_start(args)
        elif args.daemon_cmd == "stop":
            cmd_daemon_stop(args)
        elif args.daemon_cmd == "status":
            cmd_daemon_status(args)
        else:
            parser.parse_args(["daemon", "--help"])
    elif args.command in dispatch:
        dispatch[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
