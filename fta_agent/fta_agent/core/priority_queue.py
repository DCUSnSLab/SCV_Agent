"""우선순위 송신 큐: critical > high > normal > low.

M1은 기본 정책만 구현한다: 우선순위별 유한 큐, 포화 시 오래된 것부터 드롭
(드롭 수 집계). conflation·critical의 DiskBuffer 이관은 M4에서 확장.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Optional, Tuple

PRIORITIES = ("critical", "high", "normal", "low")


class PriorityOutQueue:
    def __init__(self, maxlen_per_priority: int = 256):
        self._queues = {p: deque(maxlen=None) for p in PRIORITIES}
        self._maxlen = maxlen_per_priority
        self._cond = threading.Condition()
        self.dropped = {p: 0 for p in PRIORITIES}
        self.pushed = {p: 0 for p in PRIORITIES}

    def push(self, item: Any, priority: str) -> None:
        if priority not in self._queues:
            raise ValueError(f"알 수 없는 우선순위 '{priority}' (유효: {PRIORITIES})")
        with self._cond:
            q = self._queues[priority]
            if len(q) >= self._maxlen:
                q.popleft()
                self.dropped[priority] += 1
            q.append(item)
            self.pushed[priority] += 1
            self._cond.notify()

    def pop(self, timeout: Optional[float] = None) -> Optional[Tuple[str, Any]]:
        """가장 높은 우선순위 항목을 (priority, item)으로 반환. 타임아웃 시 None."""
        with self._cond:
            if not self._cond.wait_for(self._nonempty, timeout=timeout):
                return None
            for p in PRIORITIES:
                if self._queues[p]:
                    return p, self._queues[p].popleft()
        return None  # pragma: no cover — wait_for 보장상 도달 불가

    def _nonempty(self) -> bool:
        return any(self._queues[p] for p in PRIORITIES)

    def qsize(self) -> dict:
        with self._cond:
            return {p: len(self._queues[p]) for p in PRIORITIES}
