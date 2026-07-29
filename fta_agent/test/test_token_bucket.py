import threading
import time

import pytest

from fta_agent.core.token_bucket import TokenBucket


def test_burst_then_throttle():
    stop = threading.Event()
    bucket = TokenBucket(kbps=80)  # 10,000 B/s, 버스트 1초=10,000 B
    assert bucket.consume(10_000, stop)  # 버스트 즉시 통과
    t0 = time.monotonic()
    assert bucket.consume(5_000, stop)   # 0.5초 리필 대기
    assert 0.3 <= time.monotonic() - t0 <= 1.5


def test_stop_event_aborts_wait():
    stop = threading.Event()
    bucket = TokenBucket(kbps=8)  # 1,000 B/s
    bucket.consume(1_000, stop)
    stop.set()
    assert bucket.consume(50_000, stop) is False


def test_invalid_rate():
    with pytest.raises(ValueError):
        TokenBucket(kbps=0)
