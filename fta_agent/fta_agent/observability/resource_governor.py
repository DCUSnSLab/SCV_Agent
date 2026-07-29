"""ResourceGovernor — 자체 CPU/메모리 감시·절제 (NFR-1.3/1.4, 02 문서 §3.8).

임계 초과 시 절제 순서: ① bulk 파이프라인 일시 정지 → ② 경고 로그.
임계의 80% 미만으로 내려오면 재개(히스테리시스). low 드롭율 증가·적응형
샘플링 하향은 v1.x 확장 훅으로 남긴다.
systemd CPUQuota/MemoryMax가 OS 레벨 백스톱을 겸한다 (deploy/ 참조).
"""
from __future__ import annotations

import logging

import psutil

logger = logging.getLogger(__name__)


class ResourceGovernor:
    def __init__(
        self,
        agent,
        cpu_limit_pct: float = 20.0,
        mem_limit_mb: float = 512.0,
        interval_sec: float = 5.0,
    ):
        self._agent = agent
        self._cpu_limit = cpu_limit_pct
        self._mem_limit = mem_limit_mb
        self._proc = psutil.Process()
        self._proc.cpu_percent()
        self._throttled = False
        self.stats = {"throttle_count": 0, "cpu_pct": 0.0, "rss_mb": 0.0}
        self._timer = agent.create_timer(interval_sec, self._check)

    def _check(self) -> None:
        cpu = self._proc.cpu_percent()
        rss_mb = self._proc.memory_info().rss / 1024 / 1024
        self.stats.update(cpu_pct=round(cpu, 1), rss_mb=round(rss_mb, 1))

        over = cpu > self._cpu_limit or rss_mb > self._mem_limit
        under = cpu < self._cpu_limit * 0.8 and rss_mb < self._mem_limit * 0.8

        if over and not self._throttled:
            self._throttled = True
            self.stats["throttle_count"] += 1
            paused = [p.name for p in self._agent.pipelines if p.msg_class == "bulk"]
            for p in self._agent.pipelines:
                if p.msg_class == "bulk":
                    p.pause()
            logger.warning(
                "리소스 임계 초과 (cpu=%.1f%%/%s%%, rss=%.0fMB/%sMB) — bulk 절제: %s",
                cpu, self._cpu_limit, rss_mb, self._mem_limit, paused,
            )
        elif self._throttled and under:
            self._throttled = False
            for p in self._agent.pipelines:
                if p.msg_class == "bulk":
                    p.resume()
            logger.info("리소스 정상화 (cpu=%.1f%%, rss=%.0fMB) — bulk 재개", cpu, rss_mb)
