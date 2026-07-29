#!/usr/bin/env python3
"""M4 단절 테스트용 발행자 — /event_counter(Int32, 2Hz 증가) + /odom(20Hz)."""
import argparse
import sys

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import Int32


class CounterPublisher(Node):
    def __init__(self, rate_hz: float):
        super().__init__("m4_counter_publisher")
        self._counter_pub = self.create_publisher(Int32, "/event_counter", 10)
        self._odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self._count = 0
        self.create_timer(1.0 / rate_hz, self._tick_counter)
        self.create_timer(0.05, self._tick_odom)

    def _tick_counter(self):
        self._counter_pub.publish(Int32(data=self._count))
        self._count += 1

    def _tick_odom(self):
        msg = Odometry()
        msg.pose.pose.position.x = float(self._count)
        self._odom_pub.publish(msg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=2.0, help="카운터 증가 Hz")
    args, ros_args = parser.parse_known_args()
    rclpy.init(args=ros_args)
    node = CounterPublisher(args.rate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
    return 0


if __name__ == "__main__":
    sys.exit(main())
