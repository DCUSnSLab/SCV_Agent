"""deadband 샘플러 — 지정 필드의 변화량이 임계값을 넘을 때만 통과 (FR-2.2).

필드 접근을 위해 메시지를 역직렬화한다 (worker 스레드에서 수행되므로
콜백 불변 조건과 무관). 고주기·대형 토픽에는 rate 샘플러를 우선 고려할 것.
"""
from __future__ import annotations

from fta_agent.core.field_path import as_number, get_field
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import SAMPLER_REGISTRY
from fta_agent.samplers.base import Decision, ISampler


@SAMPLER_REGISTRY.register("deadband")
class DeadbandSampler(ISampler):
    def __init__(self, field: str, threshold: float):
        if not field:
            raise ValueError("deadband 샘플러에는 field가 필요합니다")
        if not isinstance(threshold, (int, float)) or threshold < 0:
            raise ValueError(f"threshold는 0 이상 수치여야 합니다 (입력: {threshold!r})")
        self._field = field
        self._threshold = float(threshold)
        self._last_sent = None

    def decide(self, msg: MessageView, now: float) -> Decision:
        value = float(as_number(get_field(msg.ros_msg(), self._field), self._field))
        if self._last_sent is None or abs(value - self._last_sent) >= self._threshold:
            self._last_sent = value
            return Decision.PASS
        return Decision.DROP
