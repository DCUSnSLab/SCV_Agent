"""UplinkManager — 우선순위 큐를 드레인하여 Transport로 발행.

M1은 단순 드레인만 구현한다. 토큰버킷 대역폭 상한은 M4, 미연결 시
DiskBuffer 이관도 M4에서 확장 (현재는 드롭 집계 후 폐기).
"""
from __future__ import annotations

import logging
import threading

from fta_agent.core.priority_queue import PriorityOutQueue
from fta_agent.transports.base import ITransport, Reliability

logger = logging.getLogger(__name__)

_RELIABILITY_BY_PRIORITY = {
    "critical": Reliability.AT_LEAST_ONCE,
    "high": Reliability.AT_MOST_ONCE,
    "normal": Reliability.AT_MOST_ONCE,
    "low": Reliability.AT_MOST_ONCE,
}


class UplinkManager:
    def __init__(self, out_queue: PriorityOutQueue, transport: ITransport):
        self._queue = out_queue
        self._transport = transport
        self.stats = {"published": 0, "publish_failed": 0}
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="uplink", daemon=True)

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._worker.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.pop(timeout=0.2)
            if item is None:
                continue
            priority, (pipeline, data) = item
            ok = self._transport.publish(
                pipeline.msg_class,
                pipeline.name,
                data,
                _RELIABILITY_BY_PRIORITY[priority],
            )
            if ok:
                self.stats["published"] += 1
            else:
                # 미연결 등 발행 실패 — M4에서 DiskBuffer 이관으로 대체
                self.stats["publish_failed"] += 1
