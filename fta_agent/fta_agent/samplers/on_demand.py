"""on_demand 샘플러 — 요청 시 다음 메시지 1회 통과 (FR-2.2).

request()는 임의 스레드에서 호출 가능하다 (M3: 로컬 스냅샷 서비스,
M5: 다운링크 인터페이스가 트리거가 된다).
"""
from __future__ import annotations

import threading

from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import SAMPLER_REGISTRY
from fta_agent.samplers.base import Decision, ISampler


@SAMPLER_REGISTRY.register("on_demand")
class OnDemandSampler(ISampler):
    def __init__(self):
        self._pending = 0
        self._lock = threading.Lock()

    def request(self, count: int = 1) -> None:
        with self._lock:
            self._pending += count

    def decide(self, msg: MessageView, now: float) -> Decision:
        with self._lock:
            if self._pending > 0:
                self._pending -= 1
                return Decision.PASS
        return Decision.DROP
