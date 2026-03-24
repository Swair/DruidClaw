"""
I/O recording for session logging.

Records session I/O to log files with timestamps.
"""
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


LOG_DIR = Path(__file__).resolve().parent.parent.parent / "log"


class IORecorder:
    """
    Records session I/O to a log file with timestamps.

    Optimized for performance:
    - Uses buffered I/O (no flush on every write)
    - Flushes every N writes to reduce disk I/O overhead
    - Still ensures data is flushed on close
    """

    FLUSH_INTERVAL = 20

    def __init__(self, session_name: str, log_dir: Optional[Path] = None):
        if log_dir is None:
            log_dir = LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = log_dir / f"app_{session_name}_{ts}.log"
        self.raw_path = log_dir / f"app_{session_name}_{ts}.raw"
        self._log_f = open(self.log_path, "w", encoding="utf-8", errors="replace", buffering=1)
        self._raw_f = open(self.raw_path, "wb", buffering=0)
        self._lock = threading.Lock()
        self._write_count = 0
        self.write_header(session_name)

    def write_header(self, name: str):
        """Write session header to log file."""
        ts = datetime.now().isoformat()
        self._log_f.write(f"# DruidClaw Session: {name}\n")
        self._log_f.write(f"# Started: {ts}\n")
        self._log_f.write(f"# {'='*60}\n\n")
        self._log_f.flush()

    def record_output(self, data: bytes):
        """Record output data from session."""
        with self._lock:
            try:
                text = data.decode("utf-8", errors="replace")
                self._log_f.write(text)
            except Exception:
                pass
            self._raw_f.write(data)
            self._write_count += 1
            if self._write_count % self.FLUSH_INTERVAL == 0:
                self._log_f.flush()
                self._raw_f.flush()

    def record_input(self, data: bytes):
        """Record input data to session."""
        with self._lock:
            self._raw_f.write(b"\x01" + data)
            self._write_count += 1
            if self._write_count % self.FLUSH_INTERVAL == 0:
                self._raw_f.flush()

    def close(self):
        """Close log files and write footer."""
        with self._lock:
            ts = datetime.now().isoformat()
            try:
                self._log_f.flush()
                self._raw_f.flush()
                self._log_f.write(f"\n\n# Session ended: {ts}\n")
                self._log_f.close()
                self._raw_f.close()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


__all__ = ["IORecorder"]
