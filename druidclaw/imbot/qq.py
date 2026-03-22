"""
QQ Bot via OneBot v11 WebSocket protocol (反向/正向 WS).

Compatible with NapCatQQ, LLOneBot, go-cqhttp, and any OneBot v11 server.

Config:
  ws_url       — WebSocket URL, e.g. ws://127.0.0.1:3001
  access_token — Optional bearer token (leave empty if not set)

Interface is identical to FeishuBot so _ReplyCollector and bridge
handlers work without modification.
"""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import websockets.exceptions
from websockets.sync.client import connect as ws_connect

logger = logging.getLogger(__name__)

MAX_EVENTS = 200


class QQBot:
    """
    OneBot v11 WebSocket client.
    Runs a blocking WS loop in a daemon thread.
    """

    def __init__(self, ws_url: str, access_token: str = ""):
        self.ws_url = ws_url.strip()
        self.access_token = access_token.strip()
        self.app_id = f"qq:{ws_url}"   # display field

        self._status = "disconnected"
        self._error: Optional[str] = None
        self._connected_at: Optional[str] = None
        self._reconnect_count = 0

        self._events: list[dict] = []
        self._events_lock = threading.Lock()

        self._handlers: list[Callable] = []
        self._connect_handlers: list[Callable] = []
        self._disconnect_handlers: list[Callable] = []

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._ws = None  # active websocket connection

    # ── Public API ─────────────────────────────────────────── #

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread, daemon=True, name="qq-bot"
        )
        self._thread.start()
        logger.info(f"QQ bot starting (url={self.ws_url})")

    def stop(self):
        self._running = False
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._status = "disconnected"
        logger.info("QQ bot stopped")

    def add_handler(self, fn: Callable):
        self._handlers.append(fn)

    def add_connect_callback(self, fn: Callable):
        self._connect_handlers.append(fn)

    def add_disconnect_callback(self, fn: Callable):
        self._disconnect_handlers.append(fn)

    def get_status(self) -> dict:
        with self._events_lock:
            recent = list(self._events[-50:])
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
            total = len(self._events)
            events = self._events[after_index:] if after_index < total else []
        return {"total": total, "events": list(events)}

    def send_message(self, chat_id: str, text: str,
                     receive_id_type: str = "chat_id") -> bool:
        """
        Send a text message via OneBot v11 API.

        chat_id format:
          "group:12345"   → send_group_msg
          "private:12345" → send_private_msg
          "12345"         → auto-detect (tries group first)
        """
        try:
            if len(text) > 4000:
                text = text[-4000:] + "\n…(已截断)"

            ws = self._ws
            if ws is None:
                logger.warning("QQ bot: not connected, cannot send message")
                return False

            if chat_id.startswith("group:"):
                gid = int(chat_id[6:])
                action = "send_group_msg"
                params = {"group_id": gid, "message": text}
            elif chat_id.startswith("private:"):
                uid = int(chat_id[8:])
                action = "send_private_msg"
                params = {"user_id": uid, "message": text}
            else:
                # Fallback: treat as group_id
                try:
                    gid = int(chat_id)
                    action = "send_group_msg"
                    params = {"group_id": gid, "message": text}
                except ValueError:
                    logger.warning(f"QQ bot: unrecognized chat_id format: {chat_id}")
                    return False

            msg = json.dumps({"action": action, "params": params, "echo": "reply"})
            ws.send(msg)
            return True
        except Exception as e:
            logger.warning(f"QQ send_message error: {e}")
            return False

    # ── Internal helpers ────────────────────────────────────── #

    def _add_reply_event(self, text: str, chat_id: str):
        preview = text[:120].replace('\n', ' ')
        entry = {
            "index":   0,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "reply.sent",
            "summary": f"→ {chat_id}: {preview}",
            "raw":     {"chat_id": chat_id, "text": text[:300]},
        }
        with self._events_lock:
            entry["index"] = len(self._events)
            self._events.append(entry)
        logger.info(f"Claude→QQ [{chat_id}]: {preview[:60]}")

    def _add_system_event(self, etype: str, summary: str):
        entry = {
            "index":   0,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    f"system.{etype}",
            "summary": summary,
            "raw":     {},
        }
        with self._events_lock:
            entry["index"] = len(self._events)
            self._events.append(entry)

    def _record_message(self, event: dict):
        """Record an incoming OneBot v11 message event."""
        msg_type = event.get("message_type", "?")
        sender = event.get("sender", {})
        nickname = sender.get("nickname") or sender.get("card", "?")
        raw_msg = event.get("raw_message") or event.get("message", "")
        if isinstance(raw_msg, list):
            raw_msg = "".join(
                seg.get("data", {}).get("text", "") for seg in raw_msg
                if seg.get("type") == "text"
            )
        group_id = event.get("group_id")
        user_id = event.get("user_id", "?")
        ctx = f"group:{group_id}" if group_id else f"private:{user_id}"
        summary = f"{nickname}@{ctx}: {str(raw_msg)[:100]}"
        entry = {
            "index":   0,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "message",
            "summary": summary,
            "raw":     event,
        }
        with self._events_lock:
            entry["index"] = len(self._events)
            self._events.append(entry)
            if len(self._events) > MAX_EVENTS:
                self._events = self._events[-MAX_EVENTS:]
        logger.info(f"QQ message: {summary}")

    # ── Thread ──────────────────────────────────────────────── #

    def _build_headers(self) -> dict:
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _run_thread(self):
        while self._running:
            self._stop_event.clear()
            self._status = "connecting"
            self._error = None
            try:
                extra_headers = self._build_headers()
                with ws_connect(self.ws_url, additional_headers=extra_headers,
                                open_timeout=10) as ws:
                    self._ws = ws
                    self._status = "connected"
                    self._connected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._reconnect_count += 1
                    self._add_system_event("info", f"已连接 (第{self._reconnect_count}次)")
                    logger.info(f"QQ bot connected to {self.ws_url}")
                    for cb in list(self._connect_handlers):
                        try:
                            threading.Thread(target=cb, args=(self,), daemon=True).start()
                        except Exception:
                            pass

                    for raw in ws:
                        if not self._running:
                            break
                        try:
                            event = json.loads(raw)
                        except Exception:
                            continue

                        post_type = event.get("post_type")
                        if post_type == "message":
                            self._record_message(event)
                            for cb in list(self._handlers):
                                try:
                                    cb(event)
                                except Exception as e:
                                    logger.warning(f"QQ handler error: {e}")
                        # Ignore meta_event and api response frames silently

            except (websockets.exceptions.ConnectionClosed,
                    OSError, ConnectionRefusedError) as e:
                if not self._running:
                    break
                self._ws = None
                self._status = "error"
                self._error = str(e)
                logger.warning(f"QQ bot disconnected: {e}")
                self._add_system_event("error", f"断开: {e}")
                for cb in list(self._disconnect_handlers):
                    try:
                        threading.Thread(target=cb, args=(self,), daemon=True).start()
                    except Exception:
                        pass
                if self._running:
                    self._stop_event.wait(5)
            except Exception as e:
                if not self._running:
                    break
                self._ws = None
                self._status = "error"
                self._error = str(e)
                logger.warning(f"QQ bot error: {e}")
                self._add_system_event("error", f"错误: {e}")
                if self._running:
                    self._stop_event.wait(5)

        self._ws = None
        self._status = "disconnected"
        for cb in list(self._disconnect_handlers):
            try:
                threading.Thread(target=cb, args=(self,), daemon=True).start()
            except Exception:
                pass
        logger.info("QQ bot thread exited")
