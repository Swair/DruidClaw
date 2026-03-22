"""Tests for druidclaw.core.session.IORecorder."""
import os
import pytest
from pathlib import Path
from druidclaw.core.session import IORecorder


class TestIORecorder:
    """Test IORecorder functionality."""

    def test_init_creates_files(self, tmp_path):
        """Should create log and raw files on init."""
        recorder = IORecorder("test_session", log_dir=tmp_path)
        assert recorder.log_path.exists()
        assert recorder.raw_path.exists()
        assert "test_session" in recorder.log_path.name

    def test_write_header(self, tmp_path):
        """Should write header to log file."""
        recorder = IORecorder("my_session", log_dir=tmp_path)
        content = recorder.log_path.read_text()
        assert "# DruidClaw Session: my_session" in content
        assert "# Started:" in content

    def test_record_output(self, tmp_path):
        """Should record output to both log and raw files."""
        recorder = IORecorder("test", log_dir=tmp_path)
        test_data = b"Hello, World!\n"
        recorder.record_output(test_data)

        # Raw file should contain exact bytes
        raw_content = recorder.raw_path.read_bytes()
        assert test_data in raw_content

        # Log file should contain decoded text
        log_content = recorder.log_path.read_text()
        assert "Hello, World!" in log_content

    def test_record_input(self, tmp_path):
        """Should record input with marker to raw file."""
        recorder = IORecorder("test", log_dir=tmp_path)
        test_data = b"ls -la\n"
        recorder.record_input(test_data)

        raw_content = recorder.raw_path.read_bytes()
        # Input marker 0x01 followed by data
        assert b"\x01" + test_data in raw_content

    def test_close(self, tmp_path):
        """Should close files and write footer."""
        recorder = IORecorder("test", log_dir=tmp_path)
        recorder.record_output(b"test data")
        recorder.close()

        log_content = recorder.log_path.read_text()
        assert "# Session ended:" in log_content

    def test_context_manager_like_usage(self, tmp_path):
        """Test typical usage pattern."""
        recorder = IORecorder("session1", log_dir=tmp_path)
        recorder.record_output(b"output1\n")
        recorder.record_input(b"input1\n")
        recorder.record_output(b"output2\n")
        recorder.close()

        log_content = recorder.log_path.read_text()
        raw_content = recorder.raw_path.read_bytes()

        assert "output1" in log_content
        assert "output2" in log_content
        assert b"input1" in raw_content

    def test_log_dir_created_if_not_exists(self, tmp_path):
        """Should create log directory if it doesn't exist."""
        new_dir = tmp_path / "nested" / "logs"
        recorder = IORecorder("test", log_dir=new_dir)
        assert new_dir.exists()
        assert recorder.log_path.exists()
