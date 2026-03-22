"""
Fixed-capacity ring buffer for bytes.

Write: O(len(data)) amortized — no full-buffer copies on overflow.
Read:  O(capacity) worst-case — one or two memoryview slices.
"""

import threading


class RingBuf:
    """
    Thread-safe fixed-capacity ring buffer for bytes.

    Example
    -------
    buf = RingBuf(64 * 1024)
    buf.write(b"hello")
    data: bytes = buf.read()   # b"hello"
    """

    __slots__ = ("_buf", "_cap", "_head", "_size", "_lock")

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._cap: int = capacity
        self._buf: bytearray = bytearray(capacity)
        self._head: int = 0   # index of oldest byte
        self._size: int = 0   # number of valid bytes
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(self, data: (bytes | bytearray | memoryview)) -> None:
        """
        Append *data* to the buffer.
        If data is larger than capacity, only the last *capacity* bytes
        are kept (older data is dropped).
        """
        n = len(data)
        if n == 0:
            return
        with self._lock:
            self._write_locked(data, n)

    def _write_locked(self, data, n: int) -> None:
        cap = self._cap
        buf = self._buf

        # If incoming chunk is >= capacity, we only keep the tail
        if n >= cap:
            data = data[n - cap:]
            n = cap

        # Tail pointer = first free slot
        tail = (self._head + self._size) % cap

        first_chunk = min(n, cap - tail)      # bytes until wrap-around
        buf[tail : tail + first_chunk] = data[:first_chunk]

        if first_chunk < n:
            rest = n - first_chunk
            buf[:rest] = data[first_chunk:]

        if self._size + n <= cap:
            self._size += n
        else:
            # Buffer full — oldest data is overwritten; advance head
            overflow = self._size + n - cap
            self._head = (self._head + overflow) % cap
            self._size = cap

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def read(self) -> bytes:
        """Return all buffered bytes as a contiguous *bytes* object."""
        with self._lock:
            return self._read_locked()

    def _read_locked(self) -> bytes:
        if self._size == 0:
            return b""
        head = self._head
        size = self._size
        cap = self._cap
        end = head + size
        if end <= cap:
            return bytes(self._buf[head:end])
        # Wraps around
        return bytes(self._buf[head:]) + bytes(self._buf[: end - cap])

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------

    def clear(self) -> None:
        with self._lock:
            self._head = 0
            self._size = 0

    def __len__(self) -> int:
        with self._lock:
            return self._size

    @property
    def capacity(self) -> int:
        return self._cap

    def __repr__(self) -> str:
        return f"RingBuf(capacity={self._cap}, size={len(self)})"
