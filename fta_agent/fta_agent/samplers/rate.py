"""rate 샘플러 — 목표 주기(Hz)로 다운샘플 (FR-2.2)."""
from __future__ import annotations

from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import SAMPLER_REGISTRY
from fta_agent.samplers.base import Decision, ISampler


@SAMPLER_REGISTRY.register("rate")
class RateSampler(ISampler):
    def __init__(self, hz: float):
        if not isinstance(hz, (int, float)) or hz <= 0:
            raise ValueError(f"rate 샘플러의 hz는 양수여야 합니다 (입력: {hz!r})")
        self._interval = 1.0 / float(hz)
        self._last_pass = float("-inf")

    def decide(self, msg: MessageView, now: float) -> Decision:
        if now - self._last_pass >= self._interval:
            self._last_pass = now
            return Decision.PASS
        return Decision.DROP
