"""ICodec 인터페이스 (FR-3)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import NamedTuple

from fta_agent.core.message_view import MessageView


class EncodedPayload(NamedTuple):
    data: bytes
    encoding: str  # 수신측 디코딩 식별자 (FR-3.3) — 예: "cbor", "cdr+zstd", "jpeg"


class ICodec(ABC):
    """직렬화+압축 플러그인. 파라미터는 설정 YAML에서 주입된다."""

    @abstractmethod
    def encode(self, msg: MessageView) -> EncodedPayload:
        ...
