"""
Telegram Bot long-polling client.

Uses httpx (already installed) — no extra dependencies required.
Get a bot token from @BotFather via /newbot.

Interface is identical to FeishuBot so _ReplyCollector and bridge
handlers work without modification.
"""
from collections import deque
import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional, Deque

import httpx

logger = logging.getLogger(__name__)

MAX_EVENTS = 200
TELEGRAM_API = "https://api.telegram.org"


class TelegramBot:
    """
    Manages a Telegram bot via long-polling getUpdates.
    Runs in a daemon thread — no asyncio needed.
    """

    def __init__(self, token: str):
        self.token = token.strip()
        self.app_id = f"tg:{self.token[-8:]}"   # masked, for status display
        self._api = f"{TELEGRAM_API}/bot{self.token}"

        self._status = "disconnected"
        self._error: Optional[str] = None
        self._connected_at: Optional[str] = None
        self._reconnect_count = 0

        # Use deque for O(1) append and automatic maxlen management
        self._events: Deque[dict] = deque(maxlen=MAX_EVENTS)
        self._events_lock = threading.Lock()
        self._event_index = 0  # Monotonic index counter

        self._handlers: list[Callable] = []
        self._connect_handlers: list[Callable] = []
        self._disconnect_handlers: list[Callable] = []

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._offset = 0

    # ── Public API ─────────────────────────────────────────── #

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread, daemon=True, name="telegram-bot"
        )
        self._thread.start()
        logger.info(f"Telegram bot starting (token=…{self.token[-6:]})")

    def stop(self):
        self._running = False
        self._status = "disconnected"
        self._stop_event.set()
        logger.info("Telegram bot stopped")

    def add_handler(self, fn: Callable):
        self._handlers.append(fn)

    def add_connect_callback(self, fn: Callable):
        self._connect_handlers.append(fn)

    def add_disconnect_callback(self, fn: Callable):
        self._disconnect_handlers.append(fn)

    def get_status(self) -> dict:
        with self._events_lock:
            recent = list(self._events)[-50:] if len(self._events) > 50 else list(self._events)
        return {
            "status":          self._status,
            "error":           self._error,
            "app_id":          self.app_id,
            "connected_at":    self._connected_at,
            "reconnect_count": self._reconnect_count,
            "recent_events":   recent,
        }

    def get_events(self, after_index: int = 0) -> dict:
        with self._events_lock:
            total = self._event_index
            events_list = list(self._events)
            if after_index < total and events_list:
                start = max(0, len(events_list) - (total - after_index))
                events = events_list[start:]
            else:
                events = []
        return {"total": total, "events": events}

    def send_message(self, chat_id: str, text: str,
                     receive_id_type: str = "chat_id") -> bool:
        """Send a text message to a Telegram chat_id. Returns True on success."""
        try:
            # Telegram hard limit is 4096 chars
            if len(text) > 4000:
                text = text[-4000:] + "\n…(已截断)"
            cid = int(chat_id) if str(chat_id).lstrip('-').isdigit() else chat_id
            with httpx.Client(timeout=10) as client:
                r = client.post(
                    f"{self._api}/sendMessage",
                    json={"chat_id": cid, "text": text},
                )
                data = r.json()
                if not data.get("ok"):
                    logger.warning(f"Telegram sendMessage failed: {data.get('description')}")
                    return False
                return True
        except Exception as e:
            logger.warning(f"Telegram send_message error: {e}")
            return False

    # ── Internal helpers (same interface as FeishuBot) ──────── #

    def _add_reply_event(self, text: str, chat_id: str):
        preview = text[:120].replace('\n', ' ')
        entry = {
            "index":   self._event_index,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "reply.sent",
            "summary": f"→ {chat_id}: {preview}",
            "raw":     {"chat_id": chat_id, "text": text[:300]},
        }
        with self._events_lock:
            self._event_index += 1
            self._events.append(entry)
        logger.info(f"Claude→Telegram [{chat_id}]: {preview[:60]}")

    def _add_system_event(self, etype: str, summary: str):
        entry = {
            "index":   self._event_index,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    f"system.{etype}",
            "summary": summary,
            "raw":     {},
        }
        with self._events_lock:
            self._event_index += 1
            self._events.append(entry)

    def _record_update(self, update: dict):
        msg = (update.get("message")
               or update.get("channel_post")
               or update.get("edited_message", {}))
        chat = msg.get("chat", {})
        sender = msg.get("from", {})
        text = msg.get("text", "")
        chat_id = str(chat.get("id", "?"))
        username = sender.get("username") or sender.get("first_name", "?")
        summary = f"{username}@{chat_id}: {text[:100]}"
        entry = {
            "index":   self._event_index,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "message",
            "summary": summary,
            "raw":     update,
        }
        with self._events_lock:
            self._event_index += 1
            self._events.append(entry)  # deque automatically drops oldest when full
        logger.info(f"Telegram message: {summary}")

    # ── Thread ──────────────────────────────────────────────── #

    def _run_thread(self):
        # Verify token with getMe
        try:
            with httpx.Client(timeout=15) as client:
                r = client.get(f"{self._api}/getMe")
                data = r.json()
                if not data.get("ok"):
                    self._status = "error"
                    self._error = data.get("description", "Token 无效")
                    self._add_system_event("error", f"Token 无效: {self._error}")
                    return
                bot_info = data["result"]
                bot_name = bot_info.get("username", "?")
                self._status = "connected"
                self._connected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._reconnect_count += 1
                self._add_system_event("info", f"已连接: @{bot_name}")
                logger.info(f"Telegram bot verified: @{bot_name}")
                for cb in list(self._connect_handlers):
                    try:
                        threading.Thread(target=cb, args=(self,), daemon=True).start()
                    except Exception:
                        pass
        except Exception as e:
            self._status = "error"
            self._error = str(e)
            self._add_system_event("error", f"连接失败: {e}")
            return

        # Long-polling loop
        while self._running:
            try:
                with httpx.Client(timeout=35) as client:
                    r = client.get(
                        f"{self._api}/getUpdates",
                        params={
                            "timeout": 30,
                            "offset":  self._offset,
                            "allowed_updates": ["message"],
                        },
                    )
                if not self._running:
                    break
                data = r.json()
                if not data.get("ok"):
                    logger.warning(f"getUpdates error: {data}")
                    self._stop_event.wait(5)
                    continue
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._record_update(update)
                    for cb in list(self._handlers):
                        try:
                            cb(update)
                        except Exception as e:
                            logger.warning(f"Telegram handler error: {e}")
            except httpx.ReadTimeout:
                continue  # normal long-poll timeout
            except Exception as e:
                if not self._running:
                    break
                self._status = "error"
                self._error = str(e)
                logger.warning(f"Telegram polling error: {e}")
                self._add_system_event("error", f"轮询错误: {e}")
                self._stop_event.wait(5)
                if self._running:
                    self._status = "connected"
                    self._error = None

        self._status = "disconnected"
        for cb in list(self._disconnect_handlers):
            try:
                threading.Thread(target=cb, args=(self,), daemon=True).start()
            except Exception:
                pass
        logger.info("Telegram bot thread exited")
