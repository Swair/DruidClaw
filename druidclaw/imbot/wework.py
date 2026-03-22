"""
企业微信 (WeCom / WeWork) bot client.

Uses the WeWork application message API:
  - Receives messages via an HTTP callback (webhook) endpoint in app
  - Sends messages via WeWork REST API

Required credentials from WeWork Open Platform:
  corp_id       — 企业ID
  agent_id      — 应用ID
  corp_secret   — 应用Secret
  token         — 消息加解密 Token
  encoding_aes_key — 消息加解密 EncodingAESKey (43 chars)

Setup:
  1. Go to 企业微信管理后台 → 应用管理 → 创建应用
  2. Set callback URL to: http(s)://YOUR_HOST/webhook/wecom/{card_id}
  3. Fill Token and EncodingAESKey, enable callback

Interface is identical to FeishuBot so _ReplyCollector works without modification.
"""
from collections import deque
import base64
import hashlib
import json
import logging
import struct
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Callable, Optional, Deque

import httpx

logger = logging.getLogger(__name__)

MAX_EVENTS = 200
WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"


# ── AES decrypt helpers ──────────────────────────────────────────── #

def _pkcs7_unpad(data: bytes) -> bytes:
    pad = data[-1]
    return data[:-pad]


def _wecom_decrypt(encrypted_b64: str, encoding_aes_key: str) -> Optional[str]:
    """Decrypt a WeWork AES-CBC encrypted message."""
    try:
        from Crypto.Cipher import AES
        key = base64.b64decode(encoding_aes_key + "=")
        iv = key[:16]
        ciphertext = base64.b64decode(encrypted_b64)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plaintext = _pkcs7_unpad(cipher.decrypt(ciphertext))
        # Skip 16-byte random prefix, 4-byte length
        msg_len = struct.unpack(">I", plaintext[16:20])[0]
        msg_xml = plaintext[20:20 + msg_len].decode("utf-8")
        return msg_xml
    except Exception as e:
        logger.warning(f"WeWork decrypt error: {e}")
        return None


def _wecom_verify_signature(token: str, timestamp: str, nonce: str,
                             *extras: str) -> str:
    """Compute WeWork SHA1 signature."""
    parts = sorted([token, timestamp, nonce] + list(extras))
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


# ── WeWorkBot ─────────────────────────────────────────────────────── #

class WeWorkBot:
    """
    Manages a WeWork enterprise application bot.

    Message flow:
      1. WeWork POSTs callbacks to /webhook/wecom/{card_id}
      2. web_server calls bot.on_webhook(msg_signature, timestamp, nonce, body)
      3. bot decrypts, dispatches to handlers
      4. _ReplyCollector collects Claude output, calls send_message(user_id, text)
    """

    def __init__(self, corp_id: str, agent_id: str, corp_secret: str,
                 token: str, encoding_aes_key: str):
        self.corp_id = corp_id.strip()
        self.agent_id = agent_id.strip()
        self.corp_secret = corp_secret.strip()
        self.token = token.strip()
        self.encoding_aes_key = encoding_aes_key.strip()
        self.app_id = f"wecom:{corp_id}"  # for status display compatibility

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

        self._running = False
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────── #

    def start(self):
        if self._running:
            return
        self._running = True
        # Fetch access token to validate credentials
        threading.Thread(target=self._init_thread, daemon=True,
                         name="wecom-init").start()
        logger.info(f"WeWork bot starting (corp_id={self.corp_id})")

    def stop(self):
        self._running = False
        self._status = "disconnected"
        self._add_system_event("info", "已停止")
        for cb in list(self._disconnect_handlers):
            try:
                threading.Thread(target=cb, args=(self,), daemon=True).start()
            except Exception:
                pass
        logger.info("WeWork bot stopped")

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

    def send_message(self, to_user: str, text: str,
                     receive_id_type: str = "chat_id") -> bool:
        """
        Send a text message to a WeWork user (or | separated list of user IDs).
        Returns True on success.
        """
        try:
            if len(text) > 4000:
                text = text[-4000:] + "\n…(已截断)"
            token = self._get_access_token()
            if not token:
                return False
            payload = {
                "touser": to_user,
                "msgtype": "text",
                "agentid": int(self.agent_id),
                "text": {"content": text},
            }
            with httpx.Client(timeout=10) as client:
                r = client.post(
                    f"{WECOM_API}/message/send",
                    params={"access_token": token},
                    json=payload,
                )
                d = r.json()
                if d.get("errcode", 0) != 0:
                    logger.warning(f"WeWork send_message failed: {d}")
                    return False
                return True
        except Exception as e:
            logger.warning(f"WeWork send_message error: {e}")
            return False

    # ── Webhook entry point (called by web_server route) ───────── #

    def verify_url(self, msg_signature: str, timestamp: str,
                   nonce: str, echostr_encrypted: str) -> Optional[str]:
        """
        Handle GET verification callback from WeWork.
        Returns decrypted echostr string if signature valid, else None.
        """
        expected = _wecom_verify_signature(self.token, timestamp, nonce,
                                           echostr_encrypted)
        if expected != msg_signature:
            logger.warning(f"WeWork URL verify signature mismatch")
            return None
        return _wecom_decrypt(echostr_encrypted, self.encoding_aes_key)

    def on_webhook(self, msg_signature: str, timestamp: str,
                   nonce: str, xml_body: str) -> bool:
        """
        Handle POST callback from WeWork.
        Returns True if handled successfully.
        """
        try:
            root = ET.fromstring(xml_body)
            encrypt_node = root.find("Encrypt")
            if encrypt_node is None:
                # Plaintext mode
                msg_xml = xml_body
            else:
                # Verify signature (include encrypted message)
                expected = _wecom_verify_signature(self.token, timestamp, nonce,
                                                   encrypt_node.text)
                if expected != msg_signature:
                    logger.warning("WeWork webhook signature mismatch")
                    return False
                msg_xml = _wecom_decrypt(encrypt_node.text, self.encoding_aes_key)
                if not msg_xml:
                    return False

            msg_root = ET.fromstring(msg_xml)
            msg_type = (msg_root.findtext("MsgType") or "").lower()
            from_user = msg_root.findtext("FromUserName") or ""
            if not from_user:
                return True  # ignore system messages

            if msg_type == "text":
                content = msg_root.findtext("Content") or ""
                event_data = {
                    "type": "text",
                    "from_user": from_user,
                    "content": content,
                    "raw_xml": msg_xml,
                }
                self._record_message(event_data)
                for cb in list(self._handlers):
                    try:
                        cb(event_data)
                    except Exception as e:
                        logger.warning(f"WeWork handler error: {e}")
            elif msg_type == "image":
                pic_url  = msg_root.findtext("PicUrl")  or ""
                media_id = msg_root.findtext("MediaId") or ""
                event_data = {
                    "type": "image",
                    "from_user": from_user,
                    "pic_url": pic_url,
                    "media_id": media_id,
                    "raw_xml": msg_xml,
                }
                self._record_message(event_data)
                for cb in list(self._handlers):
                    try:
                        cb(event_data)
                    except Exception as e:
                        logger.warning(f"WeWork handler error: {e}")
            elif msg_type == "event":
                event_key = msg_root.findtext("Event") or ""
                self._add_system_event("event", f"事件: {event_key} from {from_user}")
            return True
        except Exception as e:
            logger.warning(f"WeWork webhook parse error: {e}")
            return False

    # ── Internal helpers ────────────────────────────────────────── #

    def _get_access_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if expired."""
        with self._token_lock:
            if self._access_token and time.time() < self._token_expires_at - 60:
                return self._access_token
            try:
                with httpx.Client(timeout=10) as client:
                    r = client.get(
                        f"{WECOM_API}/gettoken",
                        params={"corpid": self.corp_id,
                                "corpsecret": self.corp_secret},
                    )
                    d = r.json()
                    if d.get("errcode", 0) != 0:
                        self._error = d.get("errmsg", "获取token失败")
                        logger.warning(f"WeWork gettoken failed: {d}")
                        return None
                    self._access_token = d["access_token"]
                    self._token_expires_at = time.time() + d.get("expires_in", 7200)
                    return self._access_token
            except Exception as e:
                self._error = str(e)
                logger.warning(f"WeWork gettoken error: {e}")
                return None

    def _init_thread(self):
        """Validate credentials by fetching access token."""
        token = self._get_access_token()
        if token:
            self._status = "connected"
            self._connected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._reconnect_count += 1
            self._error = None
            self._add_system_event("info", "凭证验证成功，等待 Webhook 回调消息")
            logger.info(f"WeWork bot ready (corp_id={self.corp_id})")
            for cb in list(self._connect_handlers):
                try:
                    threading.Thread(target=cb, args=(self,), daemon=True).start()
                except Exception:
                    pass
        else:
            self._status = "error"
            self._add_system_event("error", f"凭证验证失败: {self._error}")

    def _add_reply_event(self, text: str, to_user: str):
        preview = text[:120].replace('\n', ' ')
        entry = {
            "index":   self._event_index,
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    "reply.sent",
            "summary": f"→ {to_user}: {preview}",
            "raw":     {"to_user": to_user, "text": text[:300]},
        }
        with self._events_lock:
            self._event_index += 1
            self._events.append(entry)
        logger.info(f"Claude→WeWork [{to_user}]: {preview[:60]}")

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
        from_user = data.get("from_user", "?")
        content = data.get("content", "")
        summary = f"{from_user}: {content[:100]}"
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
        logger.info(f"WeWork message: {summary}")
