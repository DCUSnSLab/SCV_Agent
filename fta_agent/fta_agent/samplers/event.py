"""event 샘플러 — 조건 충족 시 즉시 통과(PASS_AND_FLUSH) (FR-2.2).

엣지 트리거: 조건이 '거짓→참'으로 바뀌는 시점(및 changed의 값 변화 시점)에만
발화한다. 조건이 참으로 유지되는 동안 매 메시지를 통과시키지 않는다.
첫 메시지는 서버측 초기 상태 확보를 위해 통과시킨다.
"""
from __future__ import annotations

import operator

from fta_agent.core.field_path import get_field
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import SAMPLER_REGISTRY
from fta_agent.samplers.base import Decision, ISampler

_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


@SAMPLER_REGISTRY.register("event")
class EventSampler(ISampler):
    def __init__(self, field: str, condition: str = "changed", value=None):
        if not field:
            raise ValueError("event 샘플러에는 field가 필요합니다")
        if condition != "changed" and condition not in _OPS:
            raise ValueError(
                f"알 수 없는 condition '{condition}' "
                f"(유효: changed, {', '.join(_OPS)})"
            )
        if condition != "changed" and value is None:
            raise ValueError(f"condition '{condition}'에는 value가 필요합니다")
        self._field = field
        self._condition = condition
        self._value = value
        self._first = True
        self._last = None            # changed용 직전 값
        self._was_true = False       # 비교 조건용 직전 상태 (엣지 검출)

    def decide(self, msg: MessageView, now: float) -> Decision:
        current = get_field(msg.ros_msg(), self._field)

        if self._condition == "changed":
            fire = self._first or current != self._last
            self._last = current
        else:
            state = _OPS[self._condition](current, self._value)
            fire = self._first or (state and not self._was_true)
            self._was_true = state

        self._first = False
        return Decision.PASS_AND_FLUSH if fire else Decision.DROP
