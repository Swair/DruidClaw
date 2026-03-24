"""Entry point: python -m druidclaw.web"""
import os
import sys
import argparse
import signal
import uvicorn
from pathlib import Path

# Global flag for cleanup
_cleanup_done = False


def cleanup_sessions():
    """Kill all sessions and stop all IM bots."""
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True

    print("\n[清理资源...]", flush=True)

    from druidclaw.web.state import _sessions, _sessions_lock
    from druidclaw.web.bridge import (
        _stop_feishu_bot, _stop_telegram_bot, _stop_dingtalk_bot,
        _stop_qq_bot, _stop_wework_bot, remove_session
    )

    # Stop all IM bots
    _stop_feishu_bot()
    _stop_telegram_bot()
    _stop_dingtalk_bot()
    _stop_qq_bot()
    _stop_wework_bot()
    print("  - 所有 IM 机器人已停止", flush=True)

    # Kill all sessions
    with _sessions_lock:
        names = list(_sessions.keys())

    if not names:
        print("  - 没有活跃会话", flush=True)
    else:
        print(f"  - 正在清理 {len(names)} 个会话:", flush=True)
        for n in names:
            try:
                s = _sessions.get(n)
                pid = s.pid if s and hasattr(s, 'pid') else '?'
                remove_session(n, force=True)
                print(f"    • {n} (PID: {pid}) - 已杀死", flush=True)
            except Exception as e:
                print(f"    • {n} (PID: ?) - 失败：{e}", flush=True)

    print("[资源已清理]", flush=True)


def main():
    p = argparse.ArgumentParser(description="DruidClaw Web Server")
    p.add_argument("--host", default=None, help="Bind host (overrides saved config)")
    p.add_argument("--port", type=int, default=None, help="Port (overrides saved config)")
    p.add_argument("--workdir", default=".", help="Default working directory")
    p.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    p.add_argument("--passwd", default=None, metavar="PASSWORD",
                   help="Set access password (overrides DRUIDCLAW_TOKEN env var, default: dc)")
    args = p.parse_args()

    if args.passwd is not None:
        os.environ["DRUIDCLAW_TOKEN"] = args.passwd.strip()

    from druidclaw.web.routes.config import _load_config, _server_config, CONFIG_FILE
    cfg = _load_config()
    host = args.host if args.host is not None else cfg["host"]
    port = args.port if args.port is not None else cfg["port"]

    os.environ["DRUIDCLAW_WEB_HOST"] = host
    os.environ["DRUIDCLAW_WEB_PORT"] = str(port)
    _server_config["host"] = host
    _server_config["port"] = port

    _cc_token = os.environ.get("DRUIDCLAW_TOKEN", "dc").strip()
    display_host = "localhost" if host in ("0.0.0.0", "::") else host
    print(f"\n  DruidClaw Web Terminal")
    print(f"  URL:      http://{display_host}:{port}")
    print(f"  Password: {_cc_token}")
    print(f"  Config:   {CONFIG_FILE}")
    print(f"  按 Ctrl+C 停止\n")

    # Install signal handler
    def handle_signal(signum, frame):
        cleanup_sessions()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    uvicorn.run(
        "druidclaw.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
