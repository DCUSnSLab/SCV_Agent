"""Pipeline — 토픽당 1개: [입력큐] → worker(샘플링 → 인코딩 → 봉투) → 우선순위큐.

구독 콜백은 submit()으로 raw bytes만 적재하고 즉시 반환한다.
인코딩·압축은 전부 worker 스레드에서 수행된다 (불변 조건 3).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from fta_agent.core.envelope import Envelope
from fta_agent.core.message_view import MessageView
from fta_agent.core.priority_queue import PriorityOutQueue
from fta_agent.core.registry import CODEC_REGISTRY, SAMPLER_REGISTRY
from fta_agent.samplers.base import Decision

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        spec: dict,
        robot_id: str,
        out_queue: PriorityOutQueue,
        msg_class_obj: Any = None,
        input_maxsize: int = 32,
    ):
        self.name = spec["name"]
        self.topic = spec["topic"]
        self.msg_type = spec["msg_type"]
        self.priority = spec["priority"]
        self.msg_class = spec.get("msg_class", "state")  # state|event|bulk
        self._robot_id = robot_id
        self._sampler = SAMPLER_REGISTRY.create(
            spec["sampler"]["type"],
            **{k: v for k, v in spec["sampler"].items() if k != "type"},
        )
        self._codec = CODEC_REGISTRY.create(
            spec["codec"]["type"],
            **{k: v for k, v in spec["codec"].items() if k != "type"},
        )
        self._msg_class_obj = msg_class_obj
        self._out = out_queue
        self._in: queue.Queue = queue.Queue(maxsize=input_maxsize)
        self._seq = 0
        self.stats = {"in": 0, "sampled_out": 0, "encoded": 0, "drop_in_full": 0, "error": 0}
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._run, name=f"pipeline-{self.name}", daemon=True
        )

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._worker.join(timeout=2.0)

    def submit(self, raw: bytes) -> None:
        """구독 콜백 진입점 — 큐 적재 후 즉시 반환. 포화 시 드롭(집계만)."""
        self.stats["in"] += 1
        try:
            self._in.put_nowait(raw)
        except queue.Full:
            self.stats["drop_in_full"] += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._in.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._process(raw)
            except Exception:
                self.stats["error"] += 1
                logger.exception("파이프라인 '%s' 처리 오류 (메시지 폐기)", self.name)

    def _process(self, raw: bytes) -> None:
        view = MessageView(raw, self.topic, self.msg_type, self._msg_class_obj)
        decision = self._sampler.decide(view, time.time())
        if decision is Decision.DROP:
            self.stats["sampled_out"] += 1
            return
        encoded = self._codec.encode(view)
        env = Envelope(
            robot_id=self._robot_id,
            seq=self._seq,
            pipeline=self.name,
            src_topic=self.topic,
            msg_type=self.msg_type,
            stamp_ros=view.ros_stamp(),
            stamp_agent=time.time(),
            encoding=encoded.encoding,
            payload=encoded.data,
        )
        self._seq += 1
        self.stats["encoded"] += 1
        self._out.push((self, env.to_cbor()), self.priority)
