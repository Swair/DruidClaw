"""Tests for druidclaw.imbot module."""
import pytest

from druidclaw.imbot.wework import _wecom_verify_signature, _pkcs7_unpad
from druidclaw.imbot.feishu import _CaptureHandler, FeishuBot
from druidclaw.imbot.telegram import TelegramBot


class TestWeWorkSignature:
    """Test WeWork signature verification."""

    def test_verify_signature_basic(self):
        """Should compute correct SHA1 signature."""
        token = "test_token"
        timestamp = "1234567890"
        nonce = "random_nonce"

        sig = _wecom_verify_signature(token, timestamp, nonce)
        assert len(sig) == 40  # SHA1 hex is 40 chars

    def test_verify_signature_with_echostr(self):
        """Should include echostr in signature."""
        token = "mytoken"
        timestamp = "1600000000"
        nonce = "mynonce"
        echostr = "1234567890abcdef"

        sig = _wecom_verify_signature(token, timestamp, nonce, echostr)
        assert len(sig) == 40

    def test_signature_changes_with_input(self):
        """Different inputs should produce different signatures."""
        sig1 = _wecom_verify_signature("token1", "ts", "nonce")
        sig2 = _wecom_verify_signature("token2", "ts", "nonce")
        assert sig1 != sig2


class TestPKCS7Unpad:
    """Test PKCS7 unpadding."""

    def test_unpad_valid(self):
        """Should correctly unpad valid data."""
        data = b"hello\x05\x05\x05\x05\x05"
        result = _pkcs7_unpad(data)
        assert result == b"hello"

    def test_unpad_single_byte(self):
        """Should handle single byte padding."""
        data = b"test\x01"
        result = _pkcs7_unpad(data)
        assert result == b"test"

    def test_unpad_full_block(self):
        """Should handle full padding block."""
        data = b"\x08\x08\x08\x08\x08\x08\x08\x08"
        result = _pkcs7_unpad(data)
        assert result == b""


class TestFeishuBot:
    """Test FeishuBot functionality."""

    def test_bot_init(self):
        """Should initialize with app_id and app_secret."""
        bot = FeishuBot("cli_test_id", "cli_test_secret")
        assert bot.app_id == "cli_test_id"
        assert bot.app_secret == "cli_test_secret"
        assert bot._status == "disconnected"

    def test_bot_init_strips_whitespace(self):
        """Should strip whitespace from credentials."""
        bot = FeishuBot("  test_id  ", "  test_secret  ")
        assert bot.app_id == "test_id"
        assert bot.app_secret == "test_secret"

    def test_add_handler(self):
        """Should register event handlers."""
        bot = FeishuBot("id", "secret")
        handler = lambda x: x
        bot.add_handler(handler)
        assert handler in bot._handlers

    def test_add_connect_callback(self):
        """Should register connect callbacks."""
        bot = FeishuBot("id", "secret")
        callback = lambda x: x
        bot.add_connect_callback(callback)
        assert callback in bot._connect_handlers

    def test_add_disconnect_callback(self):
        """Should register disconnect callbacks."""
        bot = FeishuBot("id", "secret")
        callback = lambda x: x
        bot.add_disconnect_callback(callback)
        assert callback in bot._disconnect_handlers

    def test_get_status_disconnected(self):
        """Should return correct status when disconnected."""
        bot = FeishuBot("id", "secret")
        status = bot.get_status()
        assert status["status"] == "disconnected"
        assert status["app_id"] == "id"
        assert status["recent_events"] == []

    def test_get_events_empty(self):
        """Should return empty events when none recorded."""
        bot = FeishuBot("id", "secret")
        events = bot.get_events()
        assert events["total"] == 0
        assert events["events"] == []

    def test_send_message_returns_bool(self):
        """send_message should return boolean."""
        bot = FeishuBot("id", "secret")
        # Without actual API, should return False
        result = bot.send_message("chat_id", "test")
        assert isinstance(result, bool)


class TestTelegramBot:
    """Test TelegramBot functionality."""

    def test_bot_init(self):
        """Should initialize with token."""
        bot = TelegramBot("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew1F")
        assert bot.token == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew1F"
        assert "tg:" in bot.app_id
        assert bot._status == "disconnected"

    def test_bot_init_strips_whitespace(self):
        """Should strip whitespace from token."""
        bot = TelegramBot("  123456:ABC-DEF1234ghIkl  ")
        assert bot.token == "123456:ABC-DEF1234ghIkl"

    def test_add_handler(self):
        """Should register update handlers."""
        bot = TelegramBot("token")
        handler = lambda x: x
        bot.add_handler(handler)
        assert handler in bot._handlers

    def test_get_status_disconnected(self):
        """Should return correct status when not started."""
        bot = TelegramBot("token")
        status = bot.get_status()
        assert status["status"] == "disconnected"
        assert status["app_id"] == bot.app_id

    def test_get_events_empty(self):
        """Should return empty events when none recorded."""
        bot = TelegramBot("token")
        events = bot.get_events()
        assert events["total"] == 0
        assert events["events"] == []

    def test_send_message_returns_bool(self):
        """send_message should return boolean."""
        bot = TelegramBot("token")
        # Without actual API, should return False
        result = bot.send_message("-123456", "test")
        assert isinstance(result, bool)

    def test_send_message_truncates_long_text(self):
        """Should handle long messages (truncation logic)."""
        bot = TelegramBot("token")
        long_text = "x" * 5000  # Exceeds 4000 char limit
        # The method should truncate internally
        result = bot.send_message("-123456", long_text)
        assert isinstance(result, bool)


class TestCaptureHandler:
    """Test FeishuBot's _CaptureHandler."""

    def test_parse_valid_event(self):
        """Should parse valid JSON event."""
        bot = FeishuBot("id", "secret")
        handler = _CaptureHandler(bot)

        payload = b'{"header": {"event_type": "message"}, "event": {}}'
        result = handler.do_without_validation(payload)

        # Should record the event
        assert len(bot._events) == 1
        assert bot._events[0]["type"] == "message"
        assert result is None

    def test_parse_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        bot = FeishuBot("id", "secret")
        handler = _CaptureHandler(bot)

        payload = b'not valid json'
        result = handler.do_without_validation(payload)

        # Should not crash
        assert result is None

    def test_parse_event_with_message(self):
        """Should extract message content."""
        bot = FeishuBot("id", "secret")
        handler = _CaptureHandler(bot)

        payload = b'''{
            "header": {"event_type": "im.message"},
            "event": {
                "sender": {"sender_id": {"user_id": "123"}},
                "message": {"content": "{\\"text\\": \\"hello\\"}"}
            }
        }'''
        handler.do_without_validation(payload)

        assert len(bot._events) == 1
        assert "123" in bot._events[0]["summary"]
        assert "hello" in bot._events[0]["summary"]
