"""우선순위 송신 큐: critical > high > normal > low.

포화 시 정책 (02 문서 §3.5):
- low/normal: 오래된 것부터 드롭
- high: 같은 파이프라인(conflate_key)의 대기 항목을 최신값으로 교체 (conflation)
- critical: 드롭 금지 → 밀려난 항목은 overflow_handler로 넘겨 DiskBuffer에 이관

conflation은 "최신값이 이전 값을 대체할 수 있는" 상태 데이터를 전제한 최적화다.
이벤트(msg_class: event)에는 성립하지 않으므로 축출이든 conflation이든 밀려난 항목은
모두 overflow_handler를 거치게 하고, 보존 여부는 핸들러(UplinkManager)가 판단한다.

overflow_handler는 UplinkManager가 주입한다. 큐가 DiskBuffer를 직접 참조하면
불변 조건 1(구체 클래스 직접 참조 금지)에 어긋나므로 콜백으로만 연결한다.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Callable, Optional, Tuple

PRIORITIES = ("critical", "high", "normal", "low")
CONFLATE_PRIORITIES = ("high",)

# 포화로 밀려난 항목 처리기: (priority, item) -> 보존 성공 여부
OverflowHandler = Callable[[str, Any], bool]


class PriorityOutQueue:
    def __init__(self, maxlen_per_priority: int = 256):
        self._queues = {p: deque() for p in PRIORITIES}  # (conflate_key, item) 저장
        self._maxlen = maxlen_per_priority
        self._cond = threading.Condition()
        self._overflow_handler: Optional[OverflowHandler] = None
        self.dropped = {p: 0 for p in PRIORITIES}
        self.preserved = {p: 0 for p in PRIORITIES}   # 밀려났지만 버퍼로 보존된 건수
        self.conflated = {p: 0 for p in PRIORITIES}
        self.pushed = {p: 0 for p in PRIORITIES}

    def set_overflow_handler(self, handler: Optional[OverflowHandler]) -> None:
        """포화로 밀려난 항목의 처리기 등록. True를 반환하면 보존으로 집계한다."""
        self._overflow_handler = handler

    def push(self, item: Any, priority: str, conflate_key: Optional[str] = None) -> None:
        if priority not in self._queues:
            raise ValueError(f"알 수 없는 우선순위 '{priority}' (유효: {PRIORITIES})")
        evicted = None    # FIFO 축출로 밀려난 항목
        replaced = None   # conflation으로 교체된 항목
        with self._cond:
            q = self._queues[priority]
            if len(q) >= self._maxlen:
                idx = None
                if priority in CONFLATE_PRIORITIES and conflate_key is not None:
                    for i, (key, _) in enumerate(q):
                        if key == conflate_key:
                            idx = i
                            break
                if idx is not None:
                    # 같은 파이프라인의 대기 항목을 최신값으로 교체 (FIFO 위치 유지)
                    replaced = q[idx][1]
                    q[idx] = (conflate_key, item)
                else:
                    evicted = q.popleft()[1]
                    q.append((conflate_key, item))
            else:
                q.append((conflate_key, item))
            self.pushed[priority] += 1
            self._cond.notify()

        displaced = replaced if replaced is not None else evicted
        if displaced is None:
            return
        # 밀려난 항목은 conflation·축출 어느 경로든 핸들러에 넘긴다. 이벤트는 최신값으로
        # 덮어써도 되는 데이터가 아니므로 conflation 경로에서도 보존되어야 한다.
        # 핸들러는 락 밖에서 호출한다 — 디스크 I/O 동안 큐를 막으면 구독 콜백까지 밀린다.
        handled = False
        if self._overflow_handler is not None:
            handled = bool(self._overflow_handler(priority, displaced))
        with self._cond:
            if handled:
                self.preserved[priority] += 1
            elif replaced is not None:
                self.conflated[priority] += 1
            else:
                self.dropped[priority] += 1

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
