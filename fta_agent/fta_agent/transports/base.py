"""ITransport 인터페이스 (FR-4).

전송 계층은 이 인터페이스 뒤로 격리된다 — MQTT 외 Zenoh·자체 프로토콜은
구현체 추가만으로 교체 가능해야 한다 (FR-4.7).
"""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod


class ConnState(enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class Reliability(enum.Enum):
    AT_MOST_ONCE = 0   # 상태 데이터 (FR-4.3)
    AT_LEAST_ONCE = 1  # 이벤트 데이터 — 손실 불가


class ITransport(ABC):
    @abstractmethod
    def connect(self) -> None:
        """outbound 연결 개시 (비블로킹 — 단절은 정상 상황, 불변 조건 5)."""

    @abstractmethod
    def publish(
        self,
        msg_class: str,       # state | event | bulk (토픽 네임스페이스 분류)
        pipeline: str,
        data: bytes,
        reliability: Reliability,
    ) -> bool:
        """전송 시도 결과 반환. 미연결 시 False (블로킹 금지)."""

    @abstractmethod
    def state(self) -> ConnState:
        ...

    @abstractmethod
    def close(self) -> None:
        ...
