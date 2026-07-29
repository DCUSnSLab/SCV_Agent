#!/usr/bin/env python3
"""토픽 관찰자 — 수신 메시지를 YAML로 파일에 기록 (통합 테스트 검증용).

`ros2 topic echo`를 대체한다. echo는 ros2cli 데몬(XML-RPC)에 의존해 데몬 이상 시
기동 자체가 실패하고, 그러면 "기능은 정상인데 검증만 실패"하는 오탐이 난다 (이슈 A-1).
본 스크립트는 rclpy만 사용하므로 데몬과 무관하다.

사용:
  python3 topic_watcher.py --topic /goal_pose --type geometry_msgs/msg/PoseStamped \
      --out /tmp/goal.log [--qos reliable] [--ready-file /tmp/goal.ready]

--ready-file: 구독 설정을 마친 시점에 생성한다. 호출측은 이 파일을 기다렸다가
              메시지를 발행하면 구독 준비 전 발행으로 인한 유실을 피할 수 있다.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py import message_to_yaml
from rosidl_runtime_py.utilities import get_message


class TopicWatcher(Node):
    def __init__(self, topic: str, type_str: str, out_path: str, qos: QoSProfile):
        super().__init__("topic_watcher")
        self._out = open(out_path, "a", buffering=1)  # 라인 버퍼링 — 킬 당해도 기록 보존
        self._count = 0
        self.create_subscription(get_message(type_str), topic, self._on_msg, qos)

    def _on_msg(self, msg) -> None:
        self._count += 1
        self._out.write(f"--- #{self._count}\n{message_to_yaml(msg)}\n")

    def destroy_node(self) -> bool:
        self._out.close()
        return super().destroy_node()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--topic", required=True)
    p.add_argument("--type", required=True, help="pkg/msg/Type")
    p.add_argument("--out", required=True)
    p.add_argument("--qos", choices=["best_effort", "reliable"], default="reliable")
    p.add_argument("--durability", choices=["volatile", "transient_local"], default="volatile")
    p.add_argument("--depth", type=int, default=10)
    p.add_argument("--ready-file", default="")
    args, ros_args = p.parse_known_args()

    qos = QoSProfile(
        depth=args.depth,
        reliability=(ReliabilityPolicy.RELIABLE if args.qos == "reliable"
                     else ReliabilityPolicy.BEST_EFFORT),
        durability=(DurabilityPolicy.TRANSIENT_LOCAL if args.durability == "transient_local"
                    else DurabilityPolicy.VOLATILE),
    )

    rclpy.init(args=ros_args)
    node = TopicWatcher(args.topic, args.type, args.out, qos)
    if args.ready_file:
        pathlib.Path(args.ready_file).write_text("ready\n")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
    return 0


if __name__ == "__main__":
    sys.exit(main())
