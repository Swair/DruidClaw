"""
Card management REST API routes.
"""
import json
import logging
import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from druidclaw.web.state import (
    RUN_DIR,
    CARDS_FILE, _cards, _cards_lock,
    _sessions, _sessions_lock,
)
from druidclaw.web.bridge import (
    get_session, create_session, remove_session,
    _start_feishu_bot, _stop_feishu_bot, _get_feishu_bot,
    _start_telegram_bot, _stop_telegram_bot, _get_telegram_bot,
    _start_dingtalk_bot, _stop_dingtalk_bot, _get_dingtalk_bot,
    _start_qq_bot, _stop_qq_bot, _get_qq_bot,
    _start_wework_bot, _stop_wework_bot, _get_wework_bot,
)
from druidclaw.web.state import (
    _load_feishu_config, _save_feishu_config,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_IM_TYPES = ("feishu", "telegram", "dingtalk", "qq", "wework")
_DEFAULT_NAMES = {
    "claude": "session", "feishu": "飞书Bot",
    "telegram": "TelegramBot", "dingtalk": "钉钉Bot",
    "qq": "QQ Bot", "wework": "企微Bot",
}


# ── Card helpers ──────────────────────────────────────────────────

def _load_cards_from_disk():
    global _cards
    if CARDS_FILE.exists():
        try:
            data = json.loads(CARDS_FILE.read_text())
            with _cards_lock:
                _cards[:] = data if isinstance(data, list) else []
        except Exception:
            pass


def _save_cards_to_disk():
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with _cards_lock:
        CARDS_FILE.write_text(json.dumps(_cards, indent=2, ensure_ascii=False))


def _card_runtime_status(card: dict) -> dict:
    ctype = card.get("type", "claude")
    if ctype == "claude":
        s = get_session(card.get("name", ""))
        alive = bool(s and s.is_alive())
        return {"running": alive, "pid": s.pid if alive else None,
                "label": "运行中" if alive else "未启动"}
    elif ctype in ("feishu", "telegram", "dingtalk", "qq", "wework"):
        if ctype == "feishu":
            bot = _get_feishu_bot(card.get("id", "__legacy__"))
        elif ctype == "telegram":
            bot = _get_telegram_bot(card.get("id", ""))
        elif ctype == "dingtalk":
            bot = _get_dingtalk_bot(card.get("id", ""))
        elif ctype == "qq":
            bot = _get_qq_bot(card.get("id", ""))
        else:
            bot = _get_wework_bot(card.get("id", ""))
        if bot is None:
            return {"running": False, "status": "disconnected", "label": "未连接"}
        st = bot._status
        labels = {"connected": "已连接", "connecting": "连接中",
                  "error": "错误", "disconnected": "未连接"}
        return {"running": st in ("connected", "connecting"),
                "status": st, "label": labels.get(st, st),
                "error": bot._error}
    return {}


def _card_with_status(card: dict) -> dict:
    _hidden = {"app_secret", "token", "access_token", "corp_secret"}
    c = {k: v for k, v in card.items() if k not in _hidden}
    if card.get("app_secret"):
        c["has_secret"] = True
    if card.get("token"):
        c["has_token"] = True
    if card.get("access_token"):
        c["has_access_token"] = True
    return {**c, "status": _card_runtime_status(card)}


def _do_start_card(card: dict) -> dict:
    ctype = card.get("type", "claude")
    if ctype == "claude":
        name = card.get("name", "")
        workdir = card.get("workdir", ".")
        args = card.get("args", [])
        s = get_session(name)
        if not s or not s.is_alive():
            try:
                s = create_session(name=name, workdir=workdir, claude_args=args)
            except ValueError:
                remove_session(name, force=True)
                s = create_session(name=name, workdir=workdir, claude_args=args)
        return {"pid": s.pid}
    elif ctype == "feishu":
        app_id = card.get("app_id", "")
        app_secret = card.get("app_secret", "")
        # Fallback to feishu.json if card doesn't have secret yet
        if not app_secret:
            cfg = _load_feishu_config()
            app_id = app_id or cfg.get("app_id", "")
            app_secret = cfg.get("app_secret", "")
        if not app_id or not app_secret:
            raise ValueError("缺少 App ID 或 App Secret，请先编辑卡片填写凭证")
        delay = float(card.get("reply_delay", 2.0))
        auto_sess = "fbs_" + card["id"][:6]
        auto_approve = bool(card.get("auto_approve", False))
        workdir = card.get("workdir", ".")
        bot = _start_feishu_bot(app_id, app_secret,
                                auto_session_name=auto_sess,
                                card_id=card["id"],
                                auto_approve=auto_approve,
                                workdir=workdir)
        bot._reply_delay = delay
        # Also create a Claude session for the card itself
        session_name = card.get("name", f"fbs_card_{card['id'][:6]}")
        try:
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        except ValueError:
            remove_session(session_name, force=True)
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        return {"auto_session": auto_sess, "session": session_name}

    elif ctype == "telegram":
        token = card.get("token", "")
        if not token:
            raise ValueError("缺少 Bot Token，请先编辑卡片填写凭证")
        delay = float(card.get("reply_delay", 2.0))
        auto_sess = "tgb_" + card["id"][:6]
        auto_approve = bool(card.get("auto_approve", False))
        workdir = card.get("workdir", ".")
        bot = _start_telegram_bot(token, auto_session_name=auto_sess,
                                  card_id=card["id"],
                                  auto_approve=auto_approve,
                                  workdir=workdir)
        bot._reply_delay = delay
        # Also create a Claude session for the card itself
        session_name = card.get("name", f"tgb_card_{card['id'][:6]}")
        try:
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        except ValueError:
            remove_session(session_name, force=True)
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        return {"auto_session": auto_sess, "session": session_name}

    elif ctype == "dingtalk":
        app_key = card.get("app_key", "") or card.get("app_id", "")
        app_secret = card.get("app_secret", "")
        if not app_key or not app_secret:
            raise ValueError("缺少 App Key 或 App Secret，请先编辑卡片填写凭证")
        delay = float(card.get("reply_delay", 2.0))
        auto_sess = "dtb_" + card["id"][:6]
        auto_approve = bool(card.get("auto_approve", False))
        workdir = card.get("workdir", ".")
        bot = _start_dingtalk_bot(app_key, app_secret,
                                  auto_session_name=auto_sess,
                                  card_id=card["id"],
                                  auto_approve=auto_approve,
                                  workdir=workdir)
        bot._reply_delay = delay
        # Also create a Claude session for the card itself
        session_name = card.get("name", f"dtb_card_{card['id'][:6]}")
        try:
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        except ValueError:
            remove_session(session_name, force=True)
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        return {"auto_session": auto_sess, "session": session_name}

    elif ctype == "qq":
        ws_url = card.get("ws_url", "")
        access_token = card.get("access_token", "")
        if not ws_url:
            raise ValueError("缺少 WebSocket URL，请先编辑卡片填写地址")
        delay = float(card.get("reply_delay", 2.0))
        auto_sess = "qqb_" + card["id"][:6]
        auto_approve = bool(card.get("auto_approve", False))
        workdir = card.get("workdir", ".")
        bot = _start_qq_bot(ws_url, access_token,
                            auto_session_name=auto_sess,
                            card_id=card["id"],
                            auto_approve=auto_approve,
                            workdir=workdir)
        bot._reply_delay = delay
        # Also create a Claude session for the card itself
        session_name = card.get("name", f"qqb_card_{card['id'][:6]}")
        try:
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        except ValueError:
            remove_session(session_name, force=True)
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        return {"auto_session": auto_sess, "session": session_name}

    elif ctype == "wework":
        corp_id = card.get("corp_id", "")
        agent_id = card.get("agent_id", "")
        corp_secret = card.get("corp_secret", "")
        token = card.get("wework_token", "")
        aes_key = card.get("encoding_aes_key", "")
        if not corp_id or not corp_secret:
            raise ValueError("缺少 Corp ID 或 Corp Secret，请先编辑卡片填写凭证")
        delay = float(card.get("reply_delay", 2.0))
        auto_sess = "wwb_" + card["id"][:6]
        auto_approve = bool(card.get("auto_approve", False))
        workdir = card.get("workdir", ".")
        bot = _start_wework_bot(corp_id, agent_id, corp_secret, token, aes_key,
                                auto_session_name=auto_sess,
                                card_id=card["id"],
                                auto_approve=auto_approve,
                                workdir=workdir)
        bot._reply_delay = delay
        # Also create a Claude session for the card itself
        session_name = card.get("name", f"wwb_card_{card['id'][:6]}")
        try:
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        except ValueError:
            remove_session(session_name, force=True)
            create_session(name=session_name, workdir=workdir,
                          claude_args=["--dangerously-skip-permissions"] if auto_approve else [])
        return {"auto_session": auto_sess, "webhook_path": f"/webhook/wecom/{card['id']}", "session": session_name}

    return {}


def _do_stop_card(card: dict):
    ctype = card.get("type", "claude")
    if ctype == "claude":
        remove_session(card.get("name", ""), force=False)
    elif ctype == "feishu":
        _stop_feishu_bot(card_id=card.get("id", "__legacy__"))
        remove_session(card.get("name", ""), force=False)
    elif ctype == "telegram":
        _stop_telegram_bot(card_id=card.get("id", ""))
        remove_session(card.get("name", ""), force=False)
    elif ctype == "dingtalk":
        _stop_dingtalk_bot(card_id=card.get("id", ""))
        remove_session(card.get("name", ""), force=False)
    elif ctype == "qq":
        _stop_qq_bot(card_id=card.get("id", ""))
        remove_session(card.get("name", ""), force=False)
    elif ctype == "wework":
        _stop_wework_bot(card_id=card.get("id", ""))
        remove_session(card.get("name", ""), force=False)


# ── Pydantic models ───────────────────────────────────────────────

class CardCreateRequest(BaseModel):
    type: str                        # "claude"|"feishu"|"telegram"|"dingtalk"|"qq"|"wework"
    name: str = ""
    workdir: str = "."
    args: list[str] = []
    # Feishu / DingTalk
    app_id: str = ""
    app_secret: str = ""
    # DingTalk app_key
    app_key: str = ""
    # Telegram
    token: str = ""
    # QQ (OneBot v11)
    ws_url: str = ""
    access_token: str = ""
    # WeWork
    corp_id: str = ""
    agent_id: str = ""
    corp_secret: str = ""
    wework_token: str = ""
    encoding_aes_key: str = ""
    reply_delay: float = 2.0
    auto_start: bool = True
    auto_approve: bool = False   # pass --dangerously-skip-permissions to claude


class CardUpdateRequest(BaseModel):
    name: Optional[str] = None
    workdir: Optional[str] = None
    args: Optional[list[str]] = None
    app_id: Optional[str] = None
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    token: Optional[str] = None
    ws_url: Optional[str] = None
    access_token: Optional[str] = None
    corp_id: Optional[str] = None
    agent_id: Optional[str] = None
    corp_secret: Optional[str] = None
    wework_token: Optional[str] = None
    encoding_aes_key: Optional[str] = None
    reply_delay: Optional[float] = None
    auto_start: Optional[bool] = None
    auto_approve: Optional[bool] = None


# ── Card REST API ─────────────────────────────────────────────────

@router.get("/api/cards")
def api_cards_list():
    with _cards_lock:
        cards = list(_cards)
    return {"cards": [_card_with_status(c) for c in cards]}


@router.post("/api/cards")
def api_cards_create(req: CardCreateRequest):
    if req.type not in ("claude", *_IM_TYPES):
        raise HTTPException(400, f"type must be one of: claude, {', '.join(_IM_TYPES)}")
    name = req.name.strip()
    with _cards_lock:
        if not name:
            default = _DEFAULT_NAMES.get(req.type, req.type)
            if req.type == "claude":
                existing = {c["name"] for c in _cards}
                i = 1
                while f"{default}{i}" in existing:
                    i += 1
                name = f"{default}{i}"
            else:
                name = default
    card: dict = {"id": _uuid.uuid4().hex[:8], "type": req.type, "name": name}
    if req.type == "claude":
        card["workdir"] = req.workdir or "."
        card["args"] = req.args or []
    elif req.type == "feishu":
        app_id = req.app_id.strip()
        app_secret = req.app_secret.strip()
        if app_id and app_secret:
            _save_feishu_config(app_id, app_secret)
        card["app_id"]     = app_id
        card["app_secret"] = app_secret
        card["reply_delay"] = max(0.5, min(60.0, req.reply_delay))
    elif req.type == "telegram":
        card["token"]      = req.token.strip()
        card["reply_delay"] = max(0.5, min(60.0, req.reply_delay))
    elif req.type == "dingtalk":
        app_key = (req.app_key or req.app_id).strip()
        card["app_key"]    = app_key
        card["app_id"]     = app_key  # alias for display
        card["app_secret"] = req.app_secret.strip()
        card["reply_delay"] = max(0.5, min(60.0, req.reply_delay))
    elif req.type == "qq":
        card["ws_url"]      = req.ws_url.strip()
        card["access_token"] = req.access_token.strip()
        card["reply_delay"] = max(0.5, min(60.0, req.reply_delay))
    elif req.type == "wework":
        card["corp_id"]       = req.corp_id.strip()
        card["agent_id"]      = req.agent_id.strip()
        card["corp_secret"]   = req.corp_secret.strip()
        card["wework_token"]  = req.wework_token.strip()
        card["encoding_aes_key"] = req.encoding_aes_key.strip()
        card["reply_delay"]   = max(0.5, min(60.0, req.reply_delay))
    card["auto_start"] = req.auto_start
    if req.type in _IM_TYPES:
        card["auto_approve"] = req.auto_approve
        card["workdir"] = req.workdir or "."
    with _cards_lock:
        _cards.append(card)
    _save_cards_to_disk()
    if req.auto_start:
        try:
            _do_start_card(card)
        except Exception as e:
            logger.warning(f"Card auto-start failed: {e}")
    return _card_with_status(card)


@router.delete("/api/cards/{card_id}")
def api_cards_delete(card_id: str):
    with _cards_lock:
        idx = next((i for i, c in enumerate(_cards) if c["id"] == card_id), None)
        if idx is None:
            raise HTTPException(404, "Card not found")
        card = _cards.pop(idx)
    _save_cards_to_disk()
    try:
        _do_stop_card(card)
    except Exception:
        pass
    return {"ok": True}


@router.patch("/api/cards/{card_id}")
def api_cards_update(card_id: str, req: CardUpdateRequest):
    old_name = None
    with _cards_lock:
        card = next((c for c in _cards if c["id"] == card_id), None)
        if card is None:
            raise HTTPException(404, "Card not found")
        if req.name is not None:
            old_name = card["name"]
            card["name"] = req.name.strip()
        if req.workdir is not None:        card["workdir"] = req.workdir
        if req.args is not None:           card["args"] = req.args
        if req.app_id is not None:         card["app_id"] = req.app_id.strip()
        if req.app_key is not None:
            card["app_key"] = req.app_key.strip()
            card["app_id"] = req.app_key.strip()  # keep alias
        if req.reply_delay is not None:    card["reply_delay"] = max(0.5, min(60.0, req.reply_delay))
        if req.auto_start is not None:     card["auto_start"] = req.auto_start
        if req.auto_approve is not None:   card["auto_approve"] = req.auto_approve
        if req.app_secret:
            secret = req.app_secret.strip()
            card["app_secret"] = secret
            if card.get("type") == "feishu":
                _save_feishu_config(card.get("app_id", ""), secret)
        if req.token:
            card["token"] = req.token.strip()
        if req.ws_url is not None:
            card["ws_url"] = req.ws_url.strip()
        if req.access_token is not None:
            card["access_token"] = req.access_token.strip()
        if req.corp_id is not None:
            card["corp_id"] = req.corp_id.strip()
        if req.agent_id is not None:
            card["agent_id"] = req.agent_id.strip()
        if req.corp_secret:
            card["corp_secret"] = req.corp_secret.strip()
        if req.wework_token is not None:
            card["wework_token"] = req.wework_token.strip()
        if req.encoding_aes_key is not None:
            card["encoding_aes_key"] = req.encoding_aes_key.strip()
    # Rename live Claude session if name changed (outside cards_lock to avoid deadlock)
    new_name = card["name"]
    if old_name and old_name != new_name and card.get("type") == "claude":
        with _sessions_lock:
            if old_name in _sessions:
                s = _sessions.pop(old_name)
                s.name = new_name
                _sessions[new_name] = s
    # Sync reply_delay to running IM bot if changed
    if req.reply_delay is not None and card.get("type") in _IM_TYPES:
        ctype = card.get("type")
        if ctype == "feishu":
            bot = _get_feishu_bot(card_id)
        elif ctype == "telegram":
            bot = _get_telegram_bot(card_id)
        elif ctype == "dingtalk":
            bot = _get_dingtalk_bot(card_id)
        else:
            bot = _get_qq_bot(card_id)
        if bot:
            bot._reply_delay = card["reply_delay"]
    _save_cards_to_disk()
    return _card_with_status(card)


@router.post("/api/cards/{card_id}/start")
def api_cards_start(card_id: str):
    with _cards_lock:
        card = next((c for c in _cards if c["id"] == card_id), None)
    if card is None:
        raise HTTPException(404, "Card not found")
    try:
        result = _do_start_card(card)
    except (ValueError, Exception) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **result, **_card_runtime_status(card)}


@router.post("/api/cards/{card_id}/stop")
def api_cards_stop(card_id: str):
    with _cards_lock:
        card = next((c for c in _cards if c["id"] == card_id), None)
    if card is None:
        raise HTTPException(404, "Card not found")
    logger.info(f"Stopping card: {card_id} (type={card.get('type')}, name={card.get('name')})")
    _do_stop_card(card)
    # Return updated status for immediate UI refresh
    return {"ok": True, **_card_runtime_status(card)}
