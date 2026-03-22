"""Config API routes: get/set server config and restart."""
import os
import sys
import json
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from druidclaw.web.state import RUN_DIR

router = APIRouter()

CONFIG_FILE = RUN_DIR / "config.json"

_server_config: dict = {"host": "0.0.0.0", "port": 19123}


def _load_config() -> dict:
    """Load config: env vars (set by main()) → config file → defaults."""
    host = os.environ.get("DRUIDCLAW_WEB_HOST")
    port_str = os.environ.get("DRUIDCLAW_WEB_PORT")
    if host and port_str:
        _server_config["host"] = host
        _server_config["port"] = int(port_str)
        return dict(_server_config)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            _server_config.update({
                "host": str(data.get("host", "0.0.0.0")),
                "port": int(data.get("port", 19123)),
            })
        except Exception:
            pass
    return dict(_server_config)


def _save_config(host: str, port: int):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"host": host, "port": port}, indent=2))
    _server_config["host"] = host
    _server_config["port"] = port


class ConfigRequest(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None


@router.get("/api/config")
def api_get_config():
    cfg = _load_config()
    # Also expose current running bind info
    cfg["running_host"] = _server_config.get("host", "0.0.0.0")
    cfg["running_port"] = _server_config.get("port", 19123)
    # Load Anthropic config from env or file
    cfg["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", cfg.get("anthropic_api_key", ""))
    cfg["anthropic_base_url"] = os.environ.get("ANTHROPIC_BASE_URL", cfg.get("anthropic_base_url", "https://api.anthropic.com"))
    return cfg


@router.post("/api/config")
def api_set_config(req: ConfigRequest):
    """Save config. Restart=true will re-exec the server process."""
    import ipaddress

    # Load existing config
    existing = _load_config()

    # Update host/port if provided
    if req.host is not None:
        host = req.host.strip()
        if host not in ("0.0.0.0", "127.0.0.1", "localhost", "::"):
            try:
                ipaddress.ip_address(host)
            except ValueError:
                raise HTTPException(400, f"Invalid IP address: {host!r}")
        existing["host"] = host

    if req.port is not None:
        if not (1 <= req.port <= 65535):
            raise HTTPException(400, f"Invalid port: {req.port}")
        existing["port"] = req.port

    # Update Anthropic config if provided
    if req.anthropic_api_key is not None:
        existing["anthropic_api_key"] = req.anthropic_api_key
    if req.anthropic_base_url is not None:
        existing["anthropic_base_url"] = req.anthropic_base_url

    # Save config
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(existing, indent=2))
    _server_config.update(existing)

    return {"ok": True, **existing}


@router.post("/api/restart")
def api_restart():
    """Save config and restart the server process."""
    def _do_restart():
        import time, os
        time.sleep(0.8)  # Let response reach browser
        os.execv(sys.executable, [sys.executable] + sys.argv)

    t = threading.Thread(target=_do_restart, daemon=True)
    t.start()
    return {"ok": True, "message": "Restarting..."}
