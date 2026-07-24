"""UplinkManager — 우선순위 큐 드레인 + 대역폭 상한 + 단절 store & forward.

- 토큰 버킷으로 대역폭 상한 강제 (critical은 우회 — 02 문서 §4.2)
- 단절/발행 실패 시 (02 문서 §4.3):
    critical·이벤트 → DiskBuffer 전량 기록
    상태          → 파이프라인별 최신값만 유지
    bulk          → 폐기
- 재연결 감지 시 DiskBuffer 백로그부터 재전송 후 평시 복귀
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from fta_agent.core.disk_buffer import DiskBuffer
from fta_agent.core.priority_queue import PriorityOutQueue
from fta_agent.core.token_bucket import TokenBucket
from fta_agent.transports.base import ConnState, ITransport, Reliability

logger = logging.getLogger(__name__)

_RELIABILITY_BY_PRIORITY = {
    "critical": Reliability.AT_LEAST_ONCE,
    "high": Reliability.AT_MOST_ONCE,
    "normal": Reliability.AT_MOST_ONCE,
    "low": Reliability.AT_MOST_ONCE,
}


class UplinkManager:
    def __init__(
        self,
        out_queue: PriorityOutQueue,
        transport: ITransport,
        disk_buffer: Optional[DiskBuffer] = None,
        bandwidth_limit_kbps: float = 0,
    ):
        self._queue = out_queue
        self._transport = transport
        self._buffer = disk_buffer
        self._bucket = TokenBucket(bandwidth_limit_kbps) if bandwidth_limit_kbps > 0 else None
        self.stats = {
            "published": 0, "publish_failed": 0, "buffered_event": 0,
            "buffered_state": 0, "dropped_bulk": 0, "drained": 0,
        }
        self._stop = threading.Event()
        self._was_connected = False
        self._worker = threading.Thread(target=self._run, name="uplink", daemon=True)

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._worker.join(timeout=5.0)
        if self._buffer:
            self._buffer.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            connected = self._transport.state() is ConnState.CONNECTED

            # 재연결 감지 → 백로그부터 재전송 (02 §4.3)
            if connected and not self._was_connected and self._buffer:
                sent, done = self._buffer.drain(self._publish_record)
                if sent:
                    self.stats["drained"] += sent
                    logger.info("DiskBuffer 재전송: %d건 (완료=%s)", sent, done)
            self._was_connected = connected

            item = self._queue.pop(timeout=0.2)
            if item is None:
                continue
            priority, (pipeline, data) = item

            if not connected:
                self._route_offline(pipeline, priority, data)
                continue

            # 대역폭 상한 — critical은 우회 (NFR-2.5: 절제하되 연결 유지)
            if self._bucket and priority != "critical":
                if not self._bucket.consume(len(data), self._stop):
                    self._route_offline(pipeline, priority, data)
                    continue

            ok = self._transport.publish(
                pipeline.msg_class, pipeline.name, data,
                _RELIABILITY_BY_PRIORITY[priority],
            )
            if ok:
                self.stats["published"] += 1
            else:
                self.stats["publish_failed"] += 1
                self._route_offline(pipeline, priority, data)

    def _route_offline(self, pipeline, priority: str, data: bytes) -> None:
        """단절/실패 시 데이터 분류별 보존 정책 (FR-5.2~5.4)."""
        if self._buffer is None:
            self.stats["dropped_bulk"] += 1
            return
        if priority == "critical" or pipeline.msg_class == "event":
            self._buffer.append_event(pipeline.name, pipeline.msg_class, priority, data)
            self.stats["buffered_event"] += 1
        elif pipeline.msg_class == "state":
            self._buffer.put_latest_state(pipeline.name, pipeline.msg_class, priority, data)
            self.stats["buffered_state"] += 1
        else:  # bulk — 폐기
            self.stats["dropped_bulk"] += 1

    def _publish_record(self, record: dict) -> bool:
        """DiskBuffer 레코드 재전송 콜백."""
        if self._transport.state() is not ConnState.CONNECTED:
            return False
        return self._transport.publish(
            record["c"], record["p"], record["d"],
            _RELIABILITY_BY_PRIORITY.get(record["r"], Reliability.AT_LEAST_ONCE),
        )
