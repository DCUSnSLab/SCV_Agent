"""SubscriptionManager — 파이프라인 명세에 따라 generic subscription 생성.

raw=True 구독으로 CDR bytes를 그대로 받는다 (콜백에서 역직렬화 없음).
기본 QoS: best_effort / depth 5 (불변 조건 4). 파이프라인별 override 지원
(FR-1.5 — transient_local 등).
"""
from __future__ import annotations

import logging
from typing import List

from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)

from fta_agent.core.pipeline import Pipeline

logger = logging.getLogger(__name__)

_RELIABILITY = {
    "best_effort": ReliabilityPolicy.BEST_EFFORT,
    "reliable": ReliabilityPolicy.RELIABLE,
}
_DURABILITY = {
    "volatile": DurabilityPolicy.VOLATILE,
    "transient_local": DurabilityPolicy.TRANSIENT_LOCAL,
}


def make_qos(qos_spec: dict | None) -> QoSProfile:
    qos_spec = qos_spec or {}
    return QoSProfile(
        reliability=_RELIABILITY[qos_spec.get("reliability", "best_effort")],
        durability=_DURABILITY[qos_spec.get("durability", "volatile")],
        depth=qos_spec.get("depth", 5),
    )


class SubscriptionManager:
    def __init__(self, node: Node):
        self._node = node
        self._subs: List = []

    def subscribe(self, pipeline: Pipeline, msg_class_obj, qos_spec: dict | None) -> None:
        sub = self._node.create_subscription(
            msg_class_obj,
            pipeline.topic,
            lambda raw, p=pipeline: p.submit(bytes(raw)),
            make_qos(qos_spec),
            raw=True,
        )
        self._subs.append(sub)
        logger.info(
            "구독: %s (%s) → 파이프라인 '%s'", pipeline.topic, pipeline.msg_type, pipeline.name
        )
