"""
Session replay tool — replay a recorded .raw log file.
Usage:
  python -m app.core.replay <file.raw> [--speed 2.0]
"""
import os
import sys
import time
import argparse
from pathlib import Path


def replay(raw_path: Path, speed: float = 1.0, output_only: bool = True):
    """
    Replay a raw session recording.
    Format: each chunk is either:
      - Raw output bytes (PTY → terminal)
      - b"\x01" + input bytes (terminal → PTY)
    """
    data = raw_path.read_bytes()
    stdout = sys.stdout.buffer

    i = 0
    chunk_count = 0
    output_bytes = 0
    input_bytes = 0

    while i < len(data):
        # Check for input marker
        if data[i:i+1] == b"\x01":
            # Input chunk: read until next non-input byte or end
            j = i + 1
            while j < len(data) and data[j:j+1] != b"\x01":
                # Find end of input chunk (next output chunk starts)
                # Heuristic: input is typically short
                if data[j] >= 0x80 or j - i > 512:
                    break
                j += 1
            inp = data[i+1:j]
            input_bytes += len(inp)
            if not output_only:
                # Show input as cyan
                stdout.write(b"\x1b[36m")  # cyan
                stdout.write(inp)
                stdout.write(b"\x1b[0m")
                stdout.flush()
            i = j
        else:
            # Output chunk: read until input marker or end
            j = i
            while j < len(data) and data[j:j+1] != b"\x01":
                j += 1
            chunk = data[i:j]
            stdout.write(chunk)
            stdout.flush()
            output_bytes += len(chunk)
            chunk_count += 1
            if speed > 0:
                time.sleep(min(len(chunk) / 9600.0 / speed, 0.1))
            i = j

    print(
        f"\n[Replay done: {chunk_count} output chunks, "
        f"{output_bytes} output bytes, {input_bytes} input bytes]",
        file=sys.stderr
    )


def main():
    p = argparse.ArgumentParser(description="Replay a app session recording")
    p.add_argument("file", help="Path to .raw recording file")
    p.add_argument("--speed", type=float, default=2.0, help="Playback speed multiplier")
    p.add_argument("--show-input", action="store_true", help="Also show input (cyan)")
    args = p.parse_args()

    path = Path(args.file)
    if not path.exists():
        # Try finding in log dir
        from .claude import LOG_DIR
        candidates = list(LOG_DIR.glob(f"*{args.file}*"))
        if candidates:
            path = sorted(candidates)[-1]
            print(f"[replay] Using: {path}", file=sys.stderr)
        else:
            print(f"[replay] File not found: {args.file}", file=sys.stderr)
            sys.exit(1)

    replay(path, speed=args.speed, output_only=not args.show_input)


if __name__ == "__main__":
    main()
