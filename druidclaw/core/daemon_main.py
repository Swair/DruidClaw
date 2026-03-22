"""Entry point for spawning the daemon as a subprocess."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from druidclaw.core.daemon import run_daemon

if __name__ == "__main__":
    run_daemon(foreground=True)  # Already daemonized by parent
