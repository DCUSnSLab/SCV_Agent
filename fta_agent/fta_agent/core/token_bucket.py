"""토큰 버킷 — 업링크 대역폭 상한 (NFR-2.1/2.5).

상한 초과 시 연결을 붕괴시키지 않고 대기(절제)한다. critical 트래픽은
UplinkManager에서 버킷을 우회한다 (02 문서 §4.2).
"""
from __future__ import annotations

import threading
import time


class TokenBucket:
    def __init__(self, kbps: float, burst_sec: float = 1.0):
        if kbps <= 0:
            raise ValueError(f"kbps는 양수여야 합니다 (입력: {kbps!r})")
        self._rate = kbps * 1000 / 8  # bytes/sec
        self._capacity = self._rate * burst_sec
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, nbytes: int, stop_event: threading.Event, timeout: float = 30.0) -> bool:
        """nbytes만큼 토큰 확보까지 대기. stop/timeout 시 False."""
        deadline = time.monotonic() + timeout
        while not stop_event.is_set():
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= nbytes:
                    self._tokens -= nbytes
                    return True
                deficit = nbytes - self._tokens
            wait = min(deficit / self._rate, 0.5)
            if time.monotonic() + wait > deadline:
                return False
            stop_event.wait(wait)
        return False
