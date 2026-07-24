"""cdr_zstd 코덱 — ROS 원본 CDR bytes + zstd 압축 (payload 기본, D3).

역직렬화가 전혀 없으므로 typesupport 미설치 타입에도 동작한다.
수신측(서버)은 CDR을 그대로 rosbag 기록에 재사용할 수 있다 (03 문서 §3).
"""
from __future__ import annotations

import zstandard

from fta_agent.codecs.base import EncodedPayload, ICodec
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import CODEC_REGISTRY


@CODEC_REGISTRY.register("cdr_zstd")
class CdrZstdCodec(ICodec):
    def __init__(self, level: int = 3):
        if not 1 <= int(level) <= 22:
            raise ValueError(f"zstd level은 1~22 (입력: {level!r})")
        self._compressor = zstandard.ZstdCompressor(level=int(level))

    def encode(self, msg: MessageView) -> EncodedPayload:
        return EncodedPayload(
            data=self._compressor.compress(msg.raw), encoding="cdr_zstd"
        )
