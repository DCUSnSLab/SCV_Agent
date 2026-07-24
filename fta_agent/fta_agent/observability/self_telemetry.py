"""SelfTelemetry — 에이전트 자체 상태 보고 (FR-7, 02 문서 §3.9).

`fleet/{id}/agent/health`로 주기 발행(heartbeat 겸용, FR-4.4)하고,
로컬 ROS2 토픽 `/fta/health`(std_msgs/String, JSON)로도 발행해
로봇 내부에서 진단 가능하게 한다 (FR-7.2).
이 데이터는 이후 적응형 샘플링 연구의 입력이 된다.
"""
from __future__ import annotations

import json
import time

import psutil
from std_msgs.msg import String

from fta_agent.transports.base import Reliability


class SelfTelemetry:
    def __init__(self, agent, interval_sec: float = 10.0):
        self._agent = agent
        self._proc = psutil.Process()
        self._proc.cpu_percent()  # 첫 호출 기준점
        self._started = time.time()
        self._local_pub = agent.create_publisher(String, "/fta/health", 1)
        self._timer = agent.create_timer(interval_sec, self.publish)

    def build_health(self) -> dict:
        a = self._agent
        return {
            "robot_id": a.robot_id,
            "ts": time.time(),
            "uptime_sec": round(time.time() - self._started, 1),
            "conn_state": a.transport.state().value,
            "pipelines": {
                p.name: {**p.stats, "paused": p.paused} for p in a.pipelines
            },
            "uplink": dict(a.uplink.stats),
            "queue": {
                "size": a.out_queue.qsize(),
                "dropped": dict(a.out_queue.dropped),
                "conflated": dict(a.out_queue.conflated),
            },
            "buffer": a.disk_buffer.pending() if a.disk_buffer else None,
            "downlink": a.registry_sync.snapshot() if a.registry_sync else None,
            "resource": {
                "cpu_pct": self._proc.cpu_percent(),   # 지난 호출 이후 평균
                "rss_mb": round(self._proc.memory_info().rss / 1024 / 1024, 1),
                "threads": self._proc.num_threads(),
            },
        }

    def publish(self) -> None:
        health = self.build_health()
        data = json.dumps(health, ensure_ascii=False).encode("utf-8")
        # fleet/{id}/agent/health (QoS 0 — 02 §3.7)
        self._agent.transport.publish("agent", "health", data, Reliability.AT_MOST_ONCE)
        self._local_pub.publish(String(data=data.decode("utf-8")))
