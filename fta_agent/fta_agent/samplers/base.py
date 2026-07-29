"""ISampler 인터페이스 (FR-2)."""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod

from fta_agent.core.message_view import MessageView


class Decision(enum.Enum):
    PASS = "pass"
    DROP = "drop"
    PASS_AND_FLUSH = "pass_and_flush"  # 이벤트: 즉시 전송 요구


class ISampler(ABC):
    """전송 빈도/조건 결정 플러그인. 파라미터는 설정 YAML에서 주입된다."""

    @abstractmethod
    def decide(self, msg: MessageView, now: float) -> Decision:
        ...
