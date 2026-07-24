"""우선순위 송신 큐: critical > high > normal > low.

포화 시 정책 (02 문서 §3.5):
- low/normal: 오래된 것부터 드롭
- high: 같은 파이프라인(conflate_key)의 대기 항목을 최신값으로 교체 (conflation)
- critical: 드롭 금지 → DiskBuffer 이관은 M4에서 (현재는 드롭 집계)
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Optional, Tuple

PRIORITIES = ("critical", "high", "normal", "low")
CONFLATE_PRIORITIES = ("high",)


class PriorityOutQueue:
    def __init__(self, maxlen_per_priority: int = 256):
        self._queues = {p: deque() for p in PRIORITIES}  # (conflate_key, item) 저장
        self._maxlen = maxlen_per_priority
        self._cond = threading.Condition()
        self.dropped = {p: 0 for p in PRIORITIES}
        self.conflated = {p: 0 for p in PRIORITIES}
        self.pushed = {p: 0 for p in PRIORITIES}

    def push(self, item: Any, priority: str, conflate_key: Optional[str] = None) -> None:
        if priority not in self._queues:
            raise ValueError(f"알 수 없는 우선순위 '{priority}' (유효: {PRIORITIES})")
        with self._cond:
            q = self._queues[priority]
            if len(q) >= self._maxlen:
                if priority in CONFLATE_PRIORITIES and conflate_key is not None:
                    # 같은 파이프라인의 대기 항목을 최신값으로 교체 (FIFO 위치 유지)
                    for i, (key, _) in enumerate(q):
                        if key == conflate_key:
                            q[i] = (conflate_key, item)
                            self.conflated[priority] += 1
                            self.pushed[priority] += 1
                            self._cond.notify()
                            return
                q.popleft()
                self.dropped[priority] += 1
            q.append((conflate_key, item))
            self.pushed[priority] += 1
            self._cond.notify()

    def pop(self, timeout: Optional[float] = None) -> Optional[Tuple[str, Any]]:
        """가장 높은 우선순위 항목을 (priority, item)으로 반환. 타임아웃 시 None."""
        with self._cond:
            if not self._cond.wait_for(self._nonempty, timeout=timeout):
                return None
            for p in PRIORITIES:
                if self._queues[p]:
                    return p, self._queues[p].popleft()[1]
        return None  # pragma: no cover — wait_for 보장상 도달 불가

    def _nonempty(self) -> bool:
        return any(self._queues[p] for p in PRIORITIES)

    def qsize(self) -> dict:
        with self._cond:
            return {p: len(self._queues[p]) for p in PRIORITIES}
