"""FTA 에이전트 진입점.

ConfigLoader → Transport/Pipeline 조립(레지스트리 경유) → 구독 → spin.
"""
from __future__ import annotations

import argparse
import logging
import sys

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rosidl_runtime_py.utilities import get_message
from std_srvs.srv import Trigger

# 플러그인 자기등록 (구체 클래스 직접 참조 없이 import 부수효과로 등록)
import fta_agent.samplers  # noqa: F401
import fta_agent.codecs  # noqa: F401
import fta_agent.transports  # noqa: F401

from fta_agent.config.loader import ConfigError, load_config
from fta_agent.core.disk_buffer import DiskBuffer
from fta_agent.core.pipeline import Pipeline
from fta_agent.downlink.audit import AuditLog
from fta_agent.downlink.command_executor import CommandExecutor
from fta_agent.downlink.registry_sync import RegistrySyncManager
from fta_agent.observability.resource_governor import ResourceGovernor
from fta_agent.observability.self_telemetry import SelfTelemetry
from fta_agent.core.priority_queue import PriorityOutQueue
from fta_agent.core.registry import TRANSPORT_REGISTRY
from fta_agent.core.subscription_manager import SubscriptionManager
from fta_agent.core.uplink_manager import UplinkManager

logger = logging.getLogger("fta_agent")


class FtaAgent(Node):
    def __init__(self, cfg: dict):
        super().__init__("fta_agent")
        robot_id = cfg["agent"]["robot_id"]
        self.robot_id = robot_id

        transport_cfg = cfg["transport"]
        ttype = transport_cfg["type"]
        self.transport = TRANSPORT_REGISTRY.create(
            ttype, robot_id=robot_id, **transport_cfg.get(ttype, {})
        )

        self.out_queue = PriorityOutQueue(
            maxlen_per_priority=cfg["agent"].get("queue_maxlen_per_priority", 256)
        )
        buffer_cfg = cfg["agent"].get("buffer")
        self.disk_buffer = (
            DiskBuffer(buffer_cfg["dir"], buffer_cfg.get("max_disk_mb", 2048))
            if buffer_cfg
            else None
        )
        self.uplink = UplinkManager(
            self.out_queue,
            self.transport,
            disk_buffer=self.disk_buffer,
            bandwidth_limit_kbps=cfg["agent"].get("resource", {}).get(
                "bandwidth_limit_kbps", 0
            ),
        )
        self.sub_manager = SubscriptionManager(self)
        self.pipelines: list[Pipeline] = []

        for spec in cfg["pipelines"]:
            if not spec.get("enabled", True):
                logger.info("파이프라인 '%s' 비활성 (enabled: false)", spec["name"])
                continue
            try:
                msg_class_obj = get_message(spec["msg_type"])
            except (AttributeError, ModuleNotFoundError, ValueError) as e:
                raise ConfigError(
                    f"파이프라인 '{spec['name']}': msg_type '{spec['msg_type']}'의 "
                    f"typesupport를 찾을 수 없습니다 ({e})"
                ) from e
            pipeline = Pipeline(spec, robot_id, self.out_queue, msg_class_obj)
            self.pipelines.append(pipeline)
            self.sub_manager.subscribe(pipeline, msg_class_obj, spec.get("qos"))

        # 온디맨드 파이프라인용 로컬 스냅샷 서비스 (02 문서 §3.10-1)
        # request() 지원 여부는 덕 타이핑으로 판별 — 구체 샘플러 클래스 비참조
        self._snapshot_services = []
        for p in self.pipelines:
            if hasattr(p.sampler, "request"):
                self._snapshot_services.append(
                    self.create_service(
                        Trigger,
                        f"fta/request_snapshot/{p.name}",
                        self._make_snapshot_cb(p),
                    )
                )
                logger.info("스냅샷 서비스: /fta/request_snapshot/%s", p.name)

        # 다운링크 (FR-9, NFR-7) — 설정 opt-in
        dl_cfg = cfg.get("downlink", {})
        self.registry_sync = None
        self.command_executor = None
        self._audit = None
        if dl_cfg.get("enabled", False):
            self._audit = AuditLog(dl_cfg.get("audit_log", "fta_audit.jsonl"))
            self.registry_sync = RegistrySyncManager(self.transport, robot_id)
            self.command_executor = CommandExecutor(
                node=self,
                transport=self.transport,
                registry=self.registry_sync,
                audit=self._audit,
                robot_id=robot_id,
                service_timeout_sec=dl_cfg.get("command_timeout_sec", 10.0),
            )
            logger.info("다운링크 활성 — 실행 가능 대상은 레지스트리 동기화로만 결정됨")

        # 관측성 (FR-7) — health 발행 + 리소스 감시·절제
        self.telemetry = SelfTelemetry(
            self, interval_sec=cfg["agent"].get("telemetry", {}).get("interval_sec", 10.0)
        )
        res_cfg = cfg["agent"].get("resource", {})
        self.governor = (
            ResourceGovernor(
                self,
                cpu_limit_pct=res_cfg.get("cpu_limit_pct", 20.0),
                mem_limit_mb=res_cfg.get("mem_limit_mb", 512.0),
            )
            if ("cpu_limit_pct" in res_cfg or "mem_limit_mb" in res_cfg)
            else None
        )

        self._stats_timer = self.create_timer(10.0, self._log_stats)

    @staticmethod
    def _make_snapshot_cb(pipeline: Pipeline):
        def cb(request, response):
            pipeline.sampler.request()
            response.success = True
            response.message = f"'{pipeline.name}' 다음 프레임 1장 전송 예약됨"
            return response

        return cb

    def start(self) -> None:
        # 구독 등록 후 connect — retained 레지스트리를 접속 즉시 수신
        if self.registry_sync:
            self.registry_sync.start()
        if self.command_executor:
            self.command_executor.start()
        self.transport.connect()
        for p in self.pipelines:
            p.start()
        self.uplink.start()
        logger.info(
            "FTA 기동 완료: robot_id=%s, 파이프라인 %d개, transport=%s",
            self.robot_id, len(self.pipelines), self.transport.state().value,
        )

    def shutdown(self) -> None:
        for p in self.pipelines:
            p.stop()
        if self.command_executor:
            self.command_executor.stop()
        self.uplink.stop()
        self.transport.close()
        if self._audit:
            self._audit.close()

    def _log_stats(self) -> None:
        for p in self.pipelines:
            logger.info("파이프라인 '%s' 통계: %s", p.name, p.stats)
        logger.info(
            "업링크 통계: %s, 큐: %s, 드롭: %s, 포화보존: %s, conflated: %s, 버퍼: %s, 연결: %s",
            self.uplink.stats, self.out_queue.qsize(),
            self.out_queue.dropped, self.out_queue.preserved, self.out_queue.conflated,
            self.disk_buffer.pending() if self.disk_buffer else "없음",
            self.transport.state().value,
        )


class JsonLogFormatter(logging.Formatter):
    """구조화 로깅 (FR-7.3) — 라인당 JSON 1건, 수집기 friendly."""

    def format(self, record):
        import json as _json

        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return _json.dumps(entry, ensure_ascii=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FTA (Fleet Telemetry Agent)")
    parser.add_argument("--config", required=True, help="파이프라인 설정 YAML 경로")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-format", choices=["text", "json"], default="text")
    args, ros_args = parser.parse_known_args(argv)

    if args.log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logging.basicConfig(level=args.log_level.upper(), handlers=[handler])
    else:
        logging.basicConfig(
            level=args.log_level.upper(),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        logger.error("설정 오류로 기동 중단: %s", e)
        return 1

    rclpy.init(args=ros_args)
    try:
        agent = FtaAgent(cfg)
    except (ConfigError, ValueError, TypeError) as e:
        # 샘플러/코덱 파라미터 오류 포함 — 조용한 오동작 대신 즉시 종료 (FR-6.3)
        logger.error("설정 오류로 기동 중단: %s", e)
        rclpy.shutdown()
        return 1

    agent.start()
    try:
        rclpy.spin(agent)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # SIGINT/SIGTERM — 정상 종료 경로
    finally:
        agent.shutdown()
        agent.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
