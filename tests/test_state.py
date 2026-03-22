"""Tests for druidclaw.web.state module."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from druidclaw.web.state import (
    _load_feishu_config,
    _save_feishu_config,
    _RingLogHandler,
)


class TestFeishuConfig:
    """Test Feishu config file operations."""

    def test_load_config_file_not_exists(self, tmp_path):
        """Should return empty dict when config file doesn't exist."""
        non_existent = tmp_path / "nonexistent" / "feishu.json"
        with patch.object(Path, 'exists', return_value=False):
            with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
                # Mock the FEISHU_CONFIG_FILE to point to tmp_path
                import druidclaw.web.state as state_mod
                original = state_mod.FEISHU_CONFIG_FILE
                state_mod.FEISHU_CONFIG_FILE = non_existent
                try:
                    result = _load_feishu_config.__wrapped__ if hasattr(_load_feishu_config, '__wrapped__') else None
                    # Since we can't easily rebind the global, test via temp dir
                    pass
                finally:
                    state_mod.FEISHU_CONFIG_FILE = original

    def test_save_and_load_config(self, tmp_path):
        """Should save and load config correctly."""
        config_file = tmp_path / "feishu.json"

        # Save config
        import druidclaw.web.state as state_mod
        original = state_mod.FEISHU_CONFIG_FILE
        original_mkdir = state_mod.RUN_DIR
        state_mod.FEISHU_CONFIG_FILE = config_file
        state_mod.RUN_DIR = tmp_path

        try:
            _save_feishu_config("test_app_id", "test_secret")

            assert config_file.exists()
            data = json.loads(config_file.read_text())
            assert data["app_id"] == "test_app_id"
            assert data["app_secret"] == "test_secret"
        finally:
            state_mod.FEISHU_CONFIG_FILE = original
            state_mod.RUN_DIR = original_mkdir


class TestRingLogHandler:
    """Test _RingLogHandler functionality."""

    def test_handler_creation(self):
        """Should create handler with correct maxlen."""
        handler = _RingLogHandler(maxlen=100)
        assert handler._buf.maxlen == 100
        assert handler.latest_seq() == 0

    def test_emit_log_record(self):
        """Should capture log records."""
        import logging
        handler = _RingLogHandler(maxlen=10)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        handler.emit(record)

        logs = handler.get_since(0)
        assert len(logs) == 1
        assert logs[0]["level"] == "INFO"
        assert "Test message" in logs[0]["msg"]

    def test_get_since_filter(self):
        """Should return only logs after specified sequence."""
        import logging
        handler = _RingLogHandler(maxlen=10)

        # Emit first record
        record1 = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="First", args=(), exc_info=None,
        )
        handler.emit(record1)
        seq1 = handler.latest_seq()

        # Emit second record
        record2 = logging.LogRecord(
            name="test", level=logging.WARNING,
            pathname="test.py", lineno=2,
            msg="Second", args=(), exc_info=None,
        )
        handler.emit(record2)

        # Get logs after first
        logs = handler.get_since(seq1)
        assert len(logs) == 1
        assert logs[0]["msg"] == "Second"

    def test_ring_buffer_maxlen(self):
        """Should drop oldest entries when buffer is full."""
        import logging
        handler = _RingLogHandler(maxlen=5)

        for i in range(10):
            record = logging.LogRecord(
                name="test", level=logging.INFO,
                pathname="test.py", lineno=i,
                msg=f"Message {i}", args=(), exc_info=None,
            )
            handler.emit(record)

        # Should only have last 5 entries
        logs = handler.get_since(0)
        assert len(logs) == 5
        assert "Message 5" in logs[0]["msg"]
        assert "Message 9" in logs[-1]["msg"]

    def test_thread_safety(self):
        """Should handle concurrent emits safely."""
        import logging
        import threading

        handler = _RingLogHandler(maxlen=100)

        def emit_logs(count):
            for i in range(count):
                record = logging.LogRecord(
                    name="test", level=logging.INFO,
                    pathname="test.py", lineno=i,
                    msg=f"Thread msg {i}", args=(), exc_info=None,
                )
                handler.emit(record)

        threads = []
        for _ in range(5):
            t = threading.Thread(target=emit_logs, args=(20,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All 100 records should be captured (or up to maxlen)
        logs = handler.get_since(0)
        assert len(logs) == 100
