"""
Shared global state for the DruidClaw web package.
All mutable singletons live here so other modules can import them
without circular dependencies.
"""
import os
import json
import threading
import collections as _collections
import logging as _logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from druidclaw.core.session import ClaudeSession
from druidclaw.imbot.feishu import FeishuBot
from druidclaw.imbot.telegram import TelegramBot
from druidclaw.imbot.dingtalk import DingtalkBot
from druidclaw.imbot.qq import QQBot
from druidclaw.imbot.wework import WeWorkBot

logger = _logging.getLogger(__name__)

# ── In-memory log ring buffer (for header log panel) ──────

class _RingLogHandler(_logging.Handler):
    """Captures recent log records into a thread-safe ring buffer."""
    def __init__(self, maxlen: int = 200):
        super().__init__()
        self._buf: _collections.deque = _collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: _logging.LogRecord):
        try:
            msg = self.format(record)
            with self._lock:
                self._seq += 1
                self._buf.append({
                    "seq":   self._seq,
                    "time":  record.created,
                    "ts":    datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                    "level": record.levelname,
                    "msg":   msg,
                })
        except Exception:
            pass

    def get_since(self, after_seq: int = 0) -> list[dict]:
        with self._lock:
            return [e for e in self._buf if e["seq"] > after_seq]

    def latest_seq(self) -> int:
        with self._lock:
            return self._buf[-1]["seq"] if self._buf else 0

_ring_handler = _RingLogHandler(maxlen=300)
_ring_handler.setLevel(_logging.INFO)
_ring_handler.setFormatter(_logging.Formatter("%(name)s: %(message)s"))
_root_logger = _logging.getLogger()
_root_logger.setLevel(_logging.INFO)
_root_logger.addHandler(_ring_handler)

RUN_DIR = Path(os.environ.get("DRUIDCLAW_RUN_DIR", os.path.expanduser("~/.app/run")))

# ── Feishu bot registry ──────────────────────────────────────────── #

FEISHU_CONFIG_FILE = RUN_DIR / "feishu.json"
_feishu_bots: dict[str, FeishuBot] = {}   # card_id → FeishuBot
_feishu_lock = threading.Lock()


def _load_feishu_config() -> dict:
    if FEISHU_CONFIG_FILE.exists():
        try:
            return json.loads(FEISHU_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_feishu_config(app_id: str, app_secret: str):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    FEISHU_CONFIG_FILE.write_text(
        json.dumps({"app_id": app_id, "app_secret": app_secret}, indent=2)
    )


# ── Telegram bot registry ──────────────────────────────────────── #

_telegram_bots: dict[str, TelegramBot] = {}
_telegram_lock = threading.Lock()


# ── DingTalk bot registry ──────────────────────────────────────── #

_dingtalk_bots: dict[str, DingtalkBot] = {}
_dingtalk_lock = threading.Lock()


# ── QQ bot registry ────────────────────────────────────────────── #

_qq_bots: dict[str, QQBot] = {}
_qq_lock = threading.Lock()


# ── WeWork bot registry ────────────────────────────────────────────── #

_wework_bots: dict[str, WeWorkBot] = {}
_wework_lock = threading.Lock()


# ── Bridge config ─────────────────────────────────────────────── #

BRIDGE_CONFIG_FILE = RUN_DIR / "feishu_bridge.json"
_bridge_cfg: dict = {
    "reply_delay": 2.0,   # seconds of silence before sending reply
}
_bridge_cfg_lock = threading.Lock()


# ── Session registry ──────────────────────────────────────────── #

_sessions: dict[str, ClaudeSession] = {}
_sessions_lock = threading.Lock()


# ── Cards ─────────────────────────────────────────────────────── #

CARDS_FILE = RUN_DIR / "cards.json"
_cards: list[dict] = []
_cards_lock = threading.Lock()


# ── Scheduled tasks ───────────────────────────────────────────── #

TASKS_FILE = RUN_DIR / "tasks.json"
_sched_tasks: list[dict] = []
_sched_lock = threading.Lock()


# ── SSH sessions ──────────────────────────────────────────────── #

SSH_HISTORY_FILE = RUN_DIR / "ssh_history.json"
_ssh_sessions: dict[str, dict] = {}   # name → {chan, transport, thread, ...}
_ssh_sessions_lock = threading.Lock()
