"""
FastAPI application factory for DruidClaw web server.

Usage:
    from druidclaw.web.app import create_app
    app = create_app()
"""
import logging as _logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logger = _logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from druidclaw.web.state import _ring_handler, RUN_DIR
    from druidclaw.web.bridge import (
        _load_bridge_config,
        _stop_feishu_bot,
        _stop_telegram_bot,
        _stop_dingtalk_bot,
        _stop_qq_bot,
        _stop_wework_bot,
        remove_session,
    )
    from druidclaw.web.routes.cards import _load_cards_from_disk, _do_start_card
    from druidclaw.web.routes.tasks import start_scheduler
    from druidclaw.web.state import _sessions, _sessions_lock
    import json
    import os

    # Attach ring log handler to key loggers (uvicorn reconfigures root at startup)
    for _lname in ('', 'uvicorn', 'uvicorn.error', 'uvicorn.access',
                   'app', 'lark_oapi', __name__):
        _lg = _logging.getLogger(_lname)
        if _ring_handler not in _lg.handlers:
            _lg.addHandler(_ring_handler)
        _lg.setLevel(_logging.INFO)
    logger.info("DruidClaw ready — log buffer active")

    # Load claude binary override if saved
    _cc_cfg_file = RUN_DIR / "claude_config.json"
    if _cc_cfg_file.exists():
        try:
            _cc_cfg = json.loads(_cc_cfg_file.read_text())
            if _cc_cfg.get("claude_bin"):
                os.environ["CLAUDE_BIN"] = _cc_cfg["claude_bin"]
        except Exception:
            pass

    _load_bridge_config()
    _load_cards_from_disk()
    start_scheduler()

    # Auto-start cards marked auto_start
    from druidclaw.web.state import _cards, _cards_lock
    with _cards_lock:
        cards_to_start = [c for c in _cards if c.get("auto_start")]
    for card in cards_to_start:
        try:
            _do_start_card(card)
            logger.info(f"Card '{card['name']}' auto-started")
        except Exception as e:
            logger.warning(f"Card '{card['name']}' auto-start failed: {e}")

    yield

    # Cleanup
    _stop_feishu_bot()
    _stop_telegram_bot()
    _stop_dingtalk_bot()
    _stop_qq_bot()
    _stop_wework_bot()
    with _sessions_lock:
        names = list(_sessions.keys())
    for n in names:
        remove_session(n, force=True)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="DruidClaw",
        description="Claude Code Web Terminal",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import and register auth middleware
    from druidclaw.web.routes.auth import _auth_middleware
    app.middleware("http")(_auth_middleware)

    # Include all route routers
    from druidclaw.web.routes.auth import router as auth_router
    from druidclaw.web.routes.sessions import router as sessions_router
    from druidclaw.web.routes.cards import router as cards_router
    from druidclaw.web.routes.tasks import router as tasks_router
    from druidclaw.web.routes.ssh import router as ssh_router
    from druidclaw.web.routes.skills import router as skills_router
    from druidclaw.web.routes.prompts import router as prompts_router
    from druidclaw.web.routes.stats import router as stats_router
    from druidclaw.web.routes.config import router as config_router
    from druidclaw.web.routes.im import router as im_router
    from druidclaw.web.routes.history import router as history_router

    app.include_router(auth_router)
    app.include_router(sessions_router)
    app.include_router(cards_router)
    app.include_router(tasks_router)
    app.include_router(ssh_router)
    app.include_router(skills_router)
    app.include_router(prompts_router)
    app.include_router(stats_router)
    app.include_router(config_router)
    app.include_router(im_router)
    app.include_router(history_router)

    # Serve static files
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

        @app.get("/")
        def index():
            return FileResponse(str(_STATIC_DIR / "index.html"))

    return app
