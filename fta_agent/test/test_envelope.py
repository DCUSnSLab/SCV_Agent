from fta_agent.core.envelope import ENVELOPE_VERSION, Envelope


def test_cbor_roundtrip():
    env = Envelope(
        robot_id="r01",
        seq=7,
        pipeline="odom",
        src_topic="/odom",
        msg_type="nav_msgs/msg/Odometry",
        stamp_ros=(100, 500),
        stamp_agent=1234.5,
        encoding="cbor",
        payload=b"\x01\x02\x03",
    )
    decoded = Envelope.from_cbor(env.to_cbor())
    assert decoded == env
    assert decoded.version == ENVELOPE_VERSION


def test_stamp_ros_none_roundtrip():
    env = Envelope(
        robot_id="r01",
        seq=0,
        pipeline="x",
        src_topic="/x",
        msg_type="std_msgs/msg/Empty",
        stamp_ros=None,
        stamp_agent=1.0,
        encoding="cbor",
        payload=b"",
    )
    assert Envelope.from_cbor(env.to_cbor()).stamp_ros is None
