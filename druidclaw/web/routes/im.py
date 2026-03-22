"""
IM (Feishu, Telegram, DingTalk, QQ, WeWork) API routes.
Includes Feishu config/connect/disconnect/status/events,
generic IM events/status, WeWork webhook, and bridge config.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query as _Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from druidclaw.web.state import (
    _bridge_cfg, _bridge_cfg_lock,
    _cards, _cards_lock,
    _load_feishu_config, _save_feishu_config,
)
from druidclaw.web.bridge import (
    _start_feishu_bot, _stop_feishu_bot, _get_feishu_bot,
    _get_telegram_bot, _get_dingtalk_bot, _get_qq_bot, _get_wework_bot,
    _load_bridge_config, _save_bridge_config,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Feishu config API ─────────────────────────────────────────────

class FeishuConfigRequest(BaseModel):
    app_id: str
    app_secret: str


@router.get("/api/feishu/config")
def api_feishu_get_config():
    cfg = _load_feishu_config()
    return {
        "app_id":     cfg.get("app_id", ""),
        "app_secret": ("*" * 8) if cfg.get("app_secret") else "",
        "configured": bool(cfg.get("app_id") and cfg.get("app_secret")),
    }


@router.post("/api/feishu/config")
def api_feishu_set_config(req: FeishuConfigRequest):
    app_id = req.app_id.strip()
    app_secret = req.app_secret.strip()
    if not app_id:
        raise HTTPException(400, "app_id 不能为空")
    if not app_secret:
        raise HTTPException(400, "app_secret 不能为空")
    _save_feishu_config(app_id, app_secret)
    return {"ok": True}


@router.post("/api/feishu/connect")
def api_feishu_connect():
    cfg = _load_feishu_config()
    if not cfg.get("app_id") or not cfg.get("app_secret"):
        raise HTTPException(400, "请先配置 app_id 和 app_secret")
    auto_sess = "fbs_" + cfg["app_id"][-6:].replace("_", "")
    _start_feishu_bot(cfg["app_id"], cfg["app_secret"],
                      auto_session_name=auto_sess, card_id="__legacy__")
    return {"ok": True, "message": "Feishu bot 已启动", "auto_session": auto_sess}


@router.post("/api/feishu/disconnect")
def api_feishu_disconnect():
    _stop_feishu_bot(card_id="__legacy__")
    return {"ok": True}


@router.get("/api/feishu/status")
def api_feishu_status(card_id: str = "__legacy__"):
    bot = _get_feishu_bot(card_id)
    if bot is None:
        return {"status": "disconnected", "app_id": "", "recent_events": []}
    return bot.get_status()


@router.get("/api/feishu/events")
def api_feishu_events(after: int = 0, card_id: str = "__legacy__"):
    """Poll for new events since index `after`."""
    bot = _get_feishu_bot(card_id)
    if bot is None:
        return {"total": 0, "events": []}
    return bot.get_events(after_index=after)


# ── Generic IM API ────────────────────────────────────────────────

def _get_im_bot(card_id: str):
    """Return the running IM bot for any card type, or None."""
    with _cards_lock:
        card = next((c for c in _cards if c["id"] == card_id), None)
    if card is None:
        return None
    ctype = card.get("type")
    if ctype == "feishu":
        return _get_feishu_bot(card_id)
    elif ctype == "telegram":
        return _get_telegram_bot(card_id)
    elif ctype == "dingtalk":
        return _get_dingtalk_bot(card_id)
    elif ctype == "qq":
        return _get_qq_bot(card_id)
    elif ctype == "wework":
        return _get_wework_bot(card_id)
    return None


@router.get("/api/im/{card_id}/events")
def api_im_events(card_id: str, after: int = 0):
    """Generic IM event poll for any card type (feishu/telegram/dingtalk/qq)."""
    # Also support legacy feishu card_id="__legacy__"
    bot = _get_im_bot(card_id) or _get_feishu_bot(card_id)
    if bot is None:
        return {"total": 0, "events": []}
    return bot.get_events(after_index=after)


@router.get("/api/im/{card_id}/status")
def api_im_status(card_id: str):
    """Generic IM status for any card type."""
    bot = _get_im_bot(card_id) or _get_feishu_bot(card_id)
    if bot is None:
        return {"status": "disconnected", "app_id": "", "recent_events": []}
    return bot.get_status()


# ── WeWork webhook routes ─────────────────────────────────────────

@router.get("/webhook/wecom/{card_id}")
def wecom_webhook_verify(
    card_id: str,
    msg_signature: str = _Query(""),
    timestamp: str = _Query(""),
    nonce: str = _Query(""),
    echostr: str = _Query(""),
):
    """WeWork URL verification (GET)."""
    bot = _get_wework_bot(card_id)
    if bot is None:
        raise HTTPException(404, "bot not found")
    result = bot.verify_url(msg_signature, timestamp, nonce, echostr)
    if result is None:
        raise HTTPException(403, "signature mismatch")
    return PlainTextResponse(result)


@router.post("/webhook/wecom/{card_id}")
async def wecom_webhook_message(
    card_id: str,
    request: Request,
    msg_signature: str = _Query(""),
    timestamp: str = _Query(""),
    nonce: str = _Query(""),
):
    """WeWork message callback (POST)."""
    bot = _get_wework_bot(card_id)
    if bot is None:
        raise HTTPException(404, "bot not found")
    body = (await request.body()).decode("utf-8", errors="replace")
    bot.on_webhook(msg_signature, timestamp, nonce, body)
    return PlainTextResponse("success")


# ── Bridge API ────────────────────────────────────────────────────

class BridgeConfigRequest(BaseModel):
    reply_delay: float = 2.0


@router.get("/api/feishu/bridge")
def api_bridge_get():
    with _bridge_cfg_lock:
        return dict(_bridge_cfg)


@router.post("/api/feishu/bridge")
def api_bridge_set(req: BridgeConfigRequest):
    delay = max(0.5, min(60.0, req.reply_delay))
    with _bridge_cfg_lock:
        _bridge_cfg["reply_delay"] = delay
    _save_bridge_config()
    return {"ok": True, **_bridge_cfg}
