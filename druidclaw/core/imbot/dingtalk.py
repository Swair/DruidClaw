"""
DingTalk (钉钉) streaming bot client.

Requires:  pip install dingtalk-stream

Uses DingTalk's streaming (推流) protocol for enterprise internal bots.
Bot credentials: App Key + App Secret from DingTalk open platform.

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
DINGTALK_API = "https://oapi.dingtalk.com"


def _get_access_token(app_key: str, app_secret: str) -> Optional[str]:
    """Fetch a short-lived access_token from DingTalk."""
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(
                f"{DINGTALK_API}/gettoken",
                params={"appkey": app_key, "appsecret": app_secret},
            )
            d = r.json()
            if d.get("errcode") == 0:
                return d.get("access_token")
            logger.warning(f"DingTalk gettoken failed: {d}")
    except Exception as e:
        logger.warning(f"DingTalk gettoken error: {e}")
    return None


class DingtalkBot:
    """
    Manages a DingTalk enterprise internal chatbot via dingtalk-stream SDK.
    Runs in a daemon thread.

    Requires the `dingtalk-stream` package:
        pip install dingtalk-stream
    """

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self.app_id = app_key  # for status display compatibility

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
        self._client = None   # dingtalk_stream client

    # ── Public API ─────────────────────────────────────────── #

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread, daemon=True, name="dingtalk-bot"
        )
        self._thread.start()
        logger.info(f"DingTalk bot starting (app_key={self.app_key})")

    def stop(self):
        self._running = False
        self._stop_event.set()
        # Stop the stream client if running
        if self._client is not None:
            try:
                self._client.stop()
            except Exception:
                pass
        self._status = "disconnected"
        logger.info("DingTalk bot stopped")

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
        """
        Send a text reply.

        chat_id may be:
          - A webhook URL (sessionWebhook from incoming message) → POST directly
          - An open_conversation_id                              → REST API
        """
        try:
            if len(text) > 4000:
                text = text[-4000:] + "\n…(已截断)"
            payload = {
                "msgtype": "text",
                "text": {"content": text},
            }
            # If chat_id looks like a webhook URL, post directly
            if chat_id.startswith("http"):
                with httpx.Client(timeout=10) as client:
                    r = client.post(chat_id, json=payload)
                    d = r.json()
                    if d.get("errcode", 0) != 0:
                        logger.warning(f"DingTalk webhook reply failed: {d}")
                        return False
                    return True
            # Otherwise use REST API with access_token
            token = _get_access_token(self.app_key, self.app_secret)
            if not token:
                logger.warning("DingTalk: could not get access_token for send_message")
                return False
            with httpx.Client(timeout=10) as client:
                r = client.post(
                    f"{DINGTALK_API}/topapi/im/chat/scencegroup/message/send_v2",
                    params={"access_token": token},
                    json={
                        "robot_code": self.app_key,
                        "send_to": {"conversation_id": chat_id},
                        "msg_param": json.dumps({"content": text}),
                        "msg_key": "sampleText",
                    },
                )
                d = r.json()
                if d.get("errcode", 0) != 0:
                    logger.warning(f"DingTalk send_message failed: {d}")
                    return False
                return True
        except Exception as e:
            logger.warning(f"DingTalk send_message error: {e}")
            return False

    # ── Internal helpers ────────────────────────────────────── #

    def _add_reply_event(self, text: str, chat_id: str):
        preview = text[:120].replace('\n', ' ')
        entry = {
            "index":   self._event_index,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "reply.sent",
            "summary": f"→ {chat_id[:20]}: {preview}",
            "raw":     {"chat_id": chat_id, "text": text[:300]},
        }
        with self._events_lock:
            self._event_index += 1
            self._events.append(entry)
        logger.info(f"Claude→DingTalk [{chat_id[:20]}]: {preview[:60]}")

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

    def _record_message(self, data: dict):
        """Record an incoming message event."""
        sender_nick = data.get("senderNick", "?")
        conversation_id = data.get("conversationId", "?")
        text_content = ""
        try:
            text_content = data.get("text", {}).get("content", "").strip()
        except Exception:
            pass
        summary = f"{sender_nick}@{conversation_id[:12]}: {text_content[:100]}"
        entry = {
            "index":   self._event_index,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "message",
            "summary": summary,
            "raw":     data,
        }
        with self._events_lock:
            self._event_index += 1
            self._events.append(entry)  # deque automatically drops oldest when full
        logger.info(f"DingTalk message: {summary}")

    # ── Thread ──────────────────────────────────────────────── #

    def _run_thread(self):
        while self._running:
            self._stop_event.clear()
            self._status = "connecting"
            self._error = None
            try:
                import dingtalk_stream as dts
            except ImportError:
                self._status = "error"
                self._error = "未安装 dingtalk-stream，请运行: pip install dingtalk-stream"
                self._add_system_event("error", self._error)
                logger.error(self._error)
                return  # Don't retry — user needs to install package

            try:
                bot_self = self
                credential = dts.Credential(self.app_key, self.app_secret)
                client = dts.DingTalkStreamClient(credential)
                self._client = client

                class _MsgHandler(dts.ChatbotHandler):
                    async def process(self, callback: dts.CallbackMessage):
                        try:
                            data = callback.data
                            # data is a dict with senderNick, text, conversationId, etc.
                            bot_self._record_message(data)
                            for cb in list(bot_self._handlers):
                                try:
                                    cb(data)
                                except Exception as e:
                                    logger.warning(f"DingTalk handler error: {e}")
                        except Exception as e:
                            logger.warning(f"DingTalk process error: {e}")
                        return dts.AckMessage.STATUS_OK, "OK"

                client.register_callback_handler(
                    dts.ChatbotTopic.TOPIC, _MsgHandler()
                )

                # Patch: on connect, update status
                _orig_before_start = getattr(client, '_before_start', None)

                def _on_connect():
                    bot_self._status = "connected"
                    bot_self._connected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    bot_self._reconnect_count += 1
                    bot_self._add_system_event("info", f"已连接 (第{bot_self._reconnect_count}次)")
                    logger.info("DingTalk bot connected")
                    for cb in list(bot_self._connect_handlers):
                        try:
                            threading.Thread(target=cb, args=(bot_self,), daemon=True).start()
                        except Exception:
                            pass

                # DingTalk stream client has a `start_forever()` method that blocks
                # We run it in a thread so we can stop it
                _conn_called = [False]

                def _run_client():
                    try:
                        # The SDK connects and calls the handlers; we fire connect cb here
                        _on_connect()
                        client.start_forever()
                    except Exception as e:
                        if bot_self._running:
                            bot_self._status = "error"
                            bot_self._error = str(e)
                            bot_self._add_system_event("error", f"断开: {e}")

                inner_t = threading.Thread(target=_run_client, daemon=True,
                                           name="dingtalk-inner")
                inner_t.start()

                # Wait until stopped or inner thread dies
                while self._running and inner_t.is_alive():
                    self._stop_event.wait(timeout=2)

                client.stop() if hasattr(client, 'stop') else None

            except Exception as e:
                if not self._running:
                    break
                self._status = "error"
                self._error = str(e)
                logger.warning(f"DingTalk bot error: {e}")
                self._add_system_event("error", f"连接失败: {e}")
                if self._running:
                    self._stop_event.wait(5)

        self._status = "disconnected"
        for cb in list(self._disconnect_handlers):
            try:
                threading.Thread(target=cb, args=(self,), daemon=True).start()
            except Exception:
                pass
        logger.info("DingTalk bot thread exited")
