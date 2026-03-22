"""Performance benchmarks for DruidClaw core modules."""
import pytest
import time


class TestAnsiStripPerformance:
    """Performance tests for ANSI stripping."""

    def test_strip_ansi_throughput(self):
        """Test ANSI strip throughput."""
        from druidclaw.web.bridge import _ANSI_CLEAN_RE

        # Simulate terminal output with ANSI codes
        text = "\x1b[31mHello\x1b[0m " * 1000
        text += "\x1b[1;32mWorld\x1b[0m " * 1000
        text += "\x1b[2J\x1b[H" * 1000
        iterations = 1000

        start = time.perf_counter()
        for _ in range(iterations):
            _ANSI_CLEAN_RE.sub('', text)
        elapsed = time.perf_counter() - start

        # Should process large text in under 2 seconds
        assert elapsed < 2.0, f"ANSI strip too slow: {elapsed:.3f}s"
        print(f"\nANSI strip throughput: {len(text) * iterations / 1024 / 1024:.1f} MB/sec")

    def test_clean_output_performance(self):
        """Test _clean_output function performance."""
        from druidclaw.web.bridge import _clean_output

        # Simulate Claude Code output with ANSI and TUI elements
        text = "⠋ Thinking...\x1b[0m\n" * 100
        text += "Some actual output\n" * 50
        text += "\x1b[?2026hSynced block\x1b[?2026l\n" * 50
        iterations = 500

        start = time.perf_counter()
        for _ in range(iterations):
            _clean_output(text)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"Clean output too slow: {elapsed:.3f}s"
        print(f"\nClean output throughput: {iterations/elapsed:.0f} ops/sec")


class TestEventRecordingPerformance:
    """Performance tests for event recording."""

    def test_feishu_event_recording(self):
        """Test Feishu bot event recording performance."""
        from druidclaw.imbot.feishu import FeishuBot

        bot = FeishuBot("test_id", "test_secret")
        iterations = 1000

        # Simulate incoming events
        event_template = {
            "header": {"event_type": "im.message"},
            "event": {
                "sender": {"sender_id": {"user_id": "123"}},
                "message": {"content": '{"text": "hello"}'},
            }
        }

        start = time.perf_counter()
        for _ in range(iterations):
            bot._record_event(event_template)
        elapsed = time.perf_counter() - start

        # Should record 1000 events in under 1 second
        assert elapsed < 1.0, f"Event recording too slow: {elapsed:.3f}s"
        print(f"\nFeishu event recording: {iterations/elapsed:.0f} events/sec")

    def test_log_handler_performance(self):
        """Test ring log handler performance."""
        import logging
        from druidclaw.web.state import _RingLogHandler

        handler = _RingLogHandler(maxlen=300)
        iterations = 1000

        start = time.perf_counter()
        for i in range(iterations):
            record = logging.LogRecord(
                name="test", level=logging.INFO,
                pathname="test.py", lineno=i,
                msg=f"Test message {i}", args=(), exc_info=None,
            )
            handler.emit(record)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"Log handler too slow: {elapsed:.3f}s"
        print(f"\nLog handler throughput: {iterations/elapsed:.0f} logs/sec")


class TestIORecorderPerformance:
    """Performance tests for IORecorder (Optimization #1)."""

    def test_io_recorder_write_latency(self, tmp_path):
        """Test IORecorder write latency - should be fast with buffered I/O."""
        from druidclaw.core.session import IORecorder

        recorder = IORecorder("perf_test", log_dir=tmp_path)
        iterations = 1000

        start = time.perf_counter()
        for _ in range(iterations):
            recorder.record_output(b"test data line\n")
        elapsed = time.perf_counter() - start

        recorder.close()

        # With buffered I/O, should complete 1000 writes in under 0.5 seconds
        # (previously would take much longer due to flush on every write)
        assert elapsed < 0.5, f"IORecorder write too slow: {elapsed:.3f}s"
        print(f"\nIORecorder write latency: {elapsed/iterations*1000:.3f} ms/write (buffered)")

    def test_io_recorder_batch_performance(self, tmp_path):
        """Test IORecorder batch write performance."""
        from druidclaw.core.session import IORecorder

        recorder = IORecorder("batch_test", log_dir=tmp_path)
        total_bytes = 0
        iterations = 5000

        start = time.perf_counter()
        for i in range(iterations):
            data = f"Line {i}: " + "x" * 100 + "\n"
            recorder.record_output(data.encode())
            total_bytes += len(data)
        elapsed = time.perf_counter() - start

        recorder.close()

        # Should handle batch writes efficiently
        assert elapsed < 1.0, f"Batch write too slow: {elapsed:.3f}s"
        throughput_mb = total_bytes / 1024 / 1024 / elapsed
        print(f"\nIORecorder batch throughput: {throughput_mb:.1f} MB/sec")

    def test_io_recorder_input_latency(self, tmp_path):
        """Test IORecorder input recording latency."""
        from druidclaw.core.session import IORecorder

        recorder = IORecorder("input_test", log_dir=tmp_path)
        iterations = 1000

        start = time.perf_counter()
        for _ in range(iterations):
            recorder.record_input(b"command\n")
        elapsed = time.perf_counter() - start

        recorder.close()

        assert elapsed < 0.5, f"Input recording too slow: {elapsed:.3f}s"
        print(f"\nIORecorder input latency: {elapsed/iterations*1000:.3f} ms/write")


class BenchmarkResult:
    """Helper to display benchmark results."""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        import time
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed = time.perf_counter() - self.start
        print(f"\n[BENCHMARK] {self.name}: {elapsed:.4f}s")


# Example usage:
# with BenchmarkResult("operation"):
#     do_something()
