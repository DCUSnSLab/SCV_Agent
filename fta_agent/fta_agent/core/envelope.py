"""공통 메시지 봉투 (02_아키텍처설계서 §3.4).

CBOR 직렬화 포맷은 서버 프로젝트와의 계약이다 — 필드 변경 시
ENVELOPE_VERSION을 올리고 03 문서의 계약 절차를 따를 것.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cbor2

ENVELOPE_VERSION = 1


@dataclass
class Envelope:
    robot_id: str
    seq: int                          # 파이프라인별 단조 증가 (손실 감지용)
    pipeline: str                     # 설정상의 name
    src_topic: str
    msg_type: str
    stamp_agent: float                # 에이전트 처리 시각, epoch sec (지연 측정용)
    encoding: str
    payload: bytes
    stamp_ros: Optional[Tuple[int, int]] = None  # (sec, nanosec) — header 없는 타입은 None
    version: int = ENVELOPE_VERSION

    def to_cbor(self) -> bytes:
        return cbor2.dumps(
            {
                "v": self.version,
                "robot_id": self.robot_id,
                "seq": self.seq,
                "pipeline": self.pipeline,
                "src_topic": self.src_topic,
                "msg_type": self.msg_type,
                "stamp_ros": list(self.stamp_ros) if self.stamp_ros else None,
                "stamp_agent": self.stamp_agent,
                "encoding": self.encoding,
                "payload": self.payload,
            }
        )

    @classmethod
    def from_cbor(cls, data: bytes) -> "Envelope":
        d = cbor2.loads(data)
        return cls(
            version=d["v"],
            robot_id=d["robot_id"],
            seq=d["seq"],
            pipeline=d["pipeline"],
            src_topic=d["src_topic"],
            msg_type=d["msg_type"],
            stamp_ros=tuple(d["stamp_ros"]) if d.get("stamp_ros") else None,
            stamp_agent=d["stamp_agent"],
            encoding=d["encoding"],
            payload=d["payload"],
        )
