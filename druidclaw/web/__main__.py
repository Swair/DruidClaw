"""Entry point: python -m druidclaw.web"""
import os
import sys
import argparse
import uvicorn
from pathlib import Path


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
