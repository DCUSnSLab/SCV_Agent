"""FTA 에이전트 진입점.

ConfigLoader → Transport/Pipeline 조립(레지스트리 경유) → 구독 → spin.
"""
from __future__ import annotations

import argparse
import logging
import sys

import rclpy
from rclpy.node import Node
from rosidl_runtime_py.utilities import get_message

# 플러그인 자기등록 (구체 클래스 직접 참조 없이 import 부수효과로 등록)
import fta_agent.samplers  # noqa: F401
import fta_agent.codecs  # noqa: F401
import fta_agent.transports  # noqa: F401

from fta_agent.config.loader import ConfigError, load_config
from fta_agent.core.pipeline import Pipeline
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
        self.uplink = UplinkManager(self.out_queue, self.transport)
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

        self._stats_timer = self.create_timer(10.0, self._log_stats)

    def start(self) -> None:
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
        self.uplink.stop()
        self.transport.close()

    def _log_stats(self) -> None:
        for p in self.pipelines:
            logger.info("파이프라인 '%s' 통계: %s", p.name, p.stats)
        logger.info(
            "업링크 통계: %s, 큐: %s, 연결: %s",
            self.uplink.stats, self.out_queue.qsize(), self.transport.state().value,
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FTA (Fleet Telemetry Agent)")
    parser.add_argument("--config", required=True, help="파이프라인 설정 YAML 경로")
    parser.add_argument("--log-level", default="INFO")
    args, ros_args = parser.parse_known_args(argv)

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
    except ConfigError as e:
        logger.error("설정 오류로 기동 중단: %s", e)
        rclpy.shutdown()
        return 1

    agent.start()
    try:
        rclpy.spin(agent)
    except KeyboardInterrupt:
        pass
    finally:
        agent.shutdown()
        agent.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
