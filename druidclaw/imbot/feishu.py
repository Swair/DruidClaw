"""
Feishu (Lark) WebSocket long-connection bot client.
Uses the official lark-oapi SDK for connection management.

The SDK (lark_oapi.ws.Client) handles:
  - POST /callback/ws/endpoint  → get wss:// URL
  - Protobuf frame encoding/decoding
  - Ping/pong heartbeat
  - Auto-reconnect

We wrap it to:
  - Run in a daemon thread with a dedicated event loop
  - Capture all events into a ring buffer
  - Track connection status
  - Dispatch to registered callbacks
"""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_EVENTS = 200


# ------------------------------------------------------------------ #
#  Minimal event handler: captures every raw event payload           #
# ------------------------------------------------------------------ #

class _CaptureHandler:
    """
    Passed to lark_oapi.ws.Client as event_handler.
    The SDK calls do_without_validation(payload_bytes) for every event.
    """
    def __init__(self, bot: "FeishuBot"):
        self._bot = bot

    def do_without_validation(self, payload: bytes):
        try:
            event = json.loads(payload.decode("utf-8"))
            self._bot._record_event(event)
            # Dispatch to external callbacks
            for cb in list(self._bot._handlers):
                try:
                    cb(event)
                except Exception as e:
                    logger.warning(f"Event handler error: {e}")
        except Exception as e:
            logger.warning(f"Event parse error: {e}")
        return None


# ------------------------------------------------------------------ #
#  FeishuBot                                                          #
# ------------------------------------------------------------------ #

class FeishuBot:
    """
    Manages a Feishu bot's WebSocket long connection via lark-oapi SDK.
    Runs in a daemon thread with its own event loop.
    """

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()

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
        self._client = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()

    # ── Public API ─────────────────────────────────────────── #

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_thread, daemon=True, name="feishu-bot"
        )
        self._thread.start()
        logger.info(f"Feishu bot starting (app_id={self.app_id})")

    def stop(self):
        self._running = False
        self._status = "disconnected"
        # Interrupt the retry sleep
        self._stop_event.set()
        # Interrupt the event loop so client.start() unblocks immediately
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        logger.info("Feishu bot stopped")

    def add_handler(self, fn: Callable):
        self._handlers.append(fn)

    def add_connect_callback(self, fn: Callable):
        """Called (in a daemon thread) when the bot successfully connects."""
        self._connect_handlers.append(fn)

    def add_disconnect_callback(self, fn: Callable):
        """Called (in a daemon thread) when the bot disconnects."""
        self._disconnect_handlers.append(fn)

    def _dispatch_connect(self):
        for cb in list(self._connect_handlers):
            try:
                cb(self)
            except Exception as e:
                logger.warning(f"Connect callback error: {e}")

    def _dispatch_disconnect(self):
        for cb in list(self._disconnect_handlers):
            try:
                cb(self)
            except Exception as e:
                logger.warning(f"Disconnect callback error: {e}")

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

    def send_message(self, receive_id: str, text: str,
                     receive_id_type: str = "chat_id") -> bool:
        """
        Send a text message back to a Feishu chat or user.
        Uses the lark_oapi REST client (not the WS connection).
        Returns True on success.
        """
        try:
            import lark_oapi as lark
            client = lark.Client.builder() \
                .app_id(self.app_id) \
                .app_secret(self.app_secret) \
                .build()

            from lark_oapi.api.im.v1 import (
                CreateMessageRequest, CreateMessageRequestBody
            )
            content = json.dumps({"text": text})
            req = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type("text")
                    .content(content)
                    .build()
                ).build()

            resp = client.im.v1.message.create(req)
            if not resp.success():
                logger.warning(
                    f"Feishu send_message failed: code={resp.code} msg={resp.msg}"
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"Feishu send_message error: {e}")
            return False

    # ── Thread entry ───────────────────────────────────────── #

    def _run_thread(self):
        """
        Run the SDK client in a dedicated event loop.
        The SDK (lark_oapi.ws.client) stores a module-level `loop` variable;
        we patch it to use our dedicated loop so it doesn't fight FastAPI's loop.
        """
        # Create dedicated loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        while self._running:
            self._stop_event.clear()
            self._status = "connecting"
            self._error = None
            try:
                # Import SDK here (after setting the loop) so its module-level
                # `loop = asyncio.get_event_loop()` picks up our loop.
                # Also patch it explicitly to be safe.
                import lark_oapi as lark
                import lark_oapi.ws.client as _ws_mod
                _ws_mod.loop = loop

                handler = _CaptureHandler(self)

                client = _StatusWrappedClient(
                    self.app_id, self.app_secret,
                    feishu_bot=self,
                    event_handler=handler,
                    log_level=lark.LogLevel.INFO,
                    auto_reconnect=True,
                )
                self._client = client
                client.start()          # blocks until loop.stop() or error

            except RuntimeError as e:
                # loop.stop() causes "Event loop stopped before Future completed"
                # This is the normal stop path — don't log or retry.
                if not self._running:
                    break
                self._status = "error"
                self._error = str(e)
                logger.warning(f"Feishu bot runtime error: {e}")
                self._add_system_event("error", f"运行错误: {e}")
                if self._running:
                    self._stop_event.wait(5)

            except Exception as e:
                if not self._running:
                    break
                self._status = "error"
                self._error = str(e)
                logger.warning(f"Feishu bot error: {e}")
                self._add_system_event("error", f"连接失败: {e}")
                if self._running:
                    self._stop_event.wait(5)

        if self._status != "disconnected":
            self._status = "disconnected"
            self._dispatch_disconnect()
        else:
            self._status = "disconnected"
        self._loop = None
        # Cancel pending tasks before closing the loop to suppress warnings
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass

    # ── Event storage ──────────────────────────────────────── #

    def _record_event(self, event: dict):
        header = event.get("header", {})
        evt_body = event.get("event", {})
        event_type = header.get("event_type", "unknown")

        msg_obj = evt_body.get("message", {})
        sender = evt_body.get("sender", {}).get("sender_id", {})
        user_id = sender.get("user_id") or sender.get("open_id", "?")

        if msg_obj:
            content_raw = msg_obj.get("content", "{}")
            try:
                content = json.loads(content_raw).get("text", content_raw)[:200]
            except Exception:
                content = content_raw[:200]
            summary = f"{user_id}: {content}"
        else:
            summary = event_type

        entry = {
            "index":   0,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    event_type,
            "summary": summary,
            "raw":     event,
        }
        with self._events_lock:
            entry["index"] = len(self._events)
            self._events.append(entry)
            if len(self._events) > MAX_EVENTS:
                self._events = self._events[-MAX_EVENTS:]
        logger.info(f"Feishu event [{event_type}]: {summary}")

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

    def _add_reply_event(self, text: str, chat_id: str):
        """Record an outgoing Claude reply as a trackable event."""
        preview = text[:120].replace('\n', ' ')
        entry = {
            "index":   0,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "reply.sent",
            "summary": f"→ {chat_id[:12]}: {preview}",
            "raw":     {"chat_id": chat_id, "text": text[:300]},
        }
        with self._events_lock:
            entry["index"] = len(self._events)
            self._events.append(entry)
        logger.info(f"Claude→Feishu [{chat_id}]: {preview[:60]}")


# ------------------------------------------------------------------ #
#  SDK subclass: hooks connect/disconnect to update status            #
# ------------------------------------------------------------------ #

class _StatusWrappedClient:
    """
    Thin wrapper around lark_oapi.ws.Client that updates FeishuBot status
    by monkey-patching the async _connect / _disconnect coroutines.
    """

    def __init__(self, app_id, app_secret, feishu_bot: FeishuBot, **kwargs):
        import lark_oapi.ws.client as _ws_mod
        self._bot = feishu_bot
        self._inner = _ws_mod.Client(app_id, app_secret, **kwargs)
        self._patch()

    def _patch(self):
        bot = self._bot
        inner = self._inner
        _orig_connect = inner._connect
        _orig_disconnect = inner._disconnect

        async def _patched_connect():
            await _orig_connect()
            bot._status = "connected"
            bot._connected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bot._reconnect_count += 1
            bot._add_system_event("info", f"已连接 (第{bot._reconnect_count}次)")
            logger.info(f"Feishu bot connected (conn_id={inner._conn_id})")
            # Dispatch connect callbacks in a daemon thread (may block/create sessions)
            threading.Thread(target=bot._dispatch_connect, daemon=True).start()

        async def _patched_disconnect():
            was_connected = (bot._status == "connected")
            await _orig_disconnect()
            if was_connected:
                bot._status = "disconnected"
                threading.Thread(target=bot._dispatch_disconnect, daemon=True).start()

        inner._connect = _patched_connect
        inner._disconnect = _patched_disconnect

    def start(self):
        self._inner.start()
