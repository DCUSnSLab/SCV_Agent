"""cbor 코덱 — ROS 메시지를 필드 단위 dict로 변환 후 CBOR 직렬화.

introspection(rosidl_runtime_py) 기반이므로 타입별 코드가 필요 없다.
로컬에 typesupport가 설치된 타입만 사용 가능 (없으면 M3의 cdr_zstd 사용).
"""
from __future__ import annotations

import cbor2
from rosidl_runtime_py.convert import message_to_ordereddict

from fta_agent.codecs.base import EncodedPayload, ICodec
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import CODEC_REGISTRY


@CODEC_REGISTRY.register("cbor")
class CborCodec(ICodec):
    def encode(self, msg: MessageView) -> EncodedPayload:
        d = message_to_ordereddict(msg.ros_msg())
        return EncodedPayload(data=cbor2.dumps(d), encoding="cbor")
