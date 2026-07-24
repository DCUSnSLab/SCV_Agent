"""파이프라인 종단(구독 제외) 단위 테스트 — ROS typesupport(nav_msgs) 필요."""
import time

import pytest

rclpy_serialization = pytest.importorskip("rclpy.serialization")

import fta_agent.samplers  # noqa: F401
import fta_agent.codecs  # noqa: F401

import cbor2
from nav_msgs.msg import Odometry

from fta_agent.core.envelope import Envelope
from fta_agent.core.message_view import MessageView
from fta_agent.core.pipeline import Pipeline
from fta_agent.core.priority_queue import PriorityOutQueue
from fta_agent.samplers.base import Decision
from fta_agent.samplers.passthrough import PassthroughSampler

SPEC = {
    "name": "odom",
    "topic": "/odom",
    "msg_type": "nav_msgs/msg/Odometry",
    "sampler": {"type": "passthrough"},
    "codec": {"type": "cbor"},
    "priority": "high",
}


def make_raw_odom(x=1.5):
    msg = Odometry()
    msg.header.stamp.sec = 100
    msg.header.stamp.nanosec = 42
    msg.pose.pose.position.x = x
    return rclpy_serialization.serialize_message(msg)


def test_passthrough_sampler_passes():
    view = MessageView(b"", "/odom", "nav_msgs/msg/Odometry")
    assert PassthroughSampler().decide(view, time.time()) is Decision.PASS


def test_pipeline_end_to_end_produces_envelope():
    out = PriorityOutQueue()
    p = Pipeline(SPEC, robot_id="r01", out_queue=out, msg_class_obj=Odometry)
    p.start()
    try:
        p.submit(make_raw_odom(x=2.5))
        item = out.pop(timeout=2.0)
    finally:
        p.stop()

    assert item is not None
    priority, (pipe, data) = item
    assert priority == "high"
    assert pipe is p

    env = Envelope.from_cbor(data)
    assert env.robot_id == "r01"
    assert env.seq == 0
    assert env.pipeline == "odom"
    assert env.stamp_ros == (100, 42)
    assert env.encoding == "cbor"

    decoded = cbor2.loads(env.payload)
    assert decoded["pose"]["pose"]["position"]["x"] == 2.5


def test_pipeline_seq_increments():
    out = PriorityOutQueue()
    p = Pipeline(SPEC, robot_id="r01", out_queue=out, msg_class_obj=Odometry)
    p.start()
    try:
        p.submit(make_raw_odom())
        p.submit(make_raw_odom())
        first = out.pop(timeout=2.0)
        second = out.pop(timeout=2.0)
    finally:
        p.stop()
    seqs = [Envelope.from_cbor(d).seq for _, (_, d) in (first, second)]
    assert seqs == [0, 1]
