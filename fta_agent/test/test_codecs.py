"""코덱 단위 테스트 — jpeg/voxel_zstd는 ROS typesupport 필요."""
import cbor2
import numpy as np
import pytest
import zstandard

import fta_agent.codecs  # noqa: F401 — 레지스트리 등록

from fta_agent.codecs.cdr_zstd import CdrZstdCodec
from fta_agent.core.message_view import MessageView


def test_cdr_zstd_roundtrip():
    raw = b"\x00\x01" + b"repetitive data " * 200
    view = MessageView(raw, "/t", "any/msg/Type")
    encoded = CdrZstdCodec(level=3).encode(view)
    assert encoded.encoding == "cdr_zstd"
    assert len(encoded.data) < len(raw)  # 반복 데이터는 압축됨
    assert zstandard.ZstdDecompressor().decompress(encoded.data) == raw


def test_cdr_zstd_invalid_level():
    with pytest.raises(ValueError):
        CdrZstdCodec(level=0)


# --- ROS 메시지 기반 (rclpy 필요) ---

rclpy_serialization = pytest.importorskip("rclpy.serialization")


def make_image_view(width=320, height=240):
    from sensor_msgs.msg import Image

    msg = Image()
    msg.height, msg.width = height, width
    msg.encoding = "rgb8"
    msg.step = width * 3
    msg.data = np.random.randint(0, 255, (height, width, 3), np.uint8).tobytes()
    raw = rclpy_serialization.serialize_message(msg)
    return MessageView(raw, "/camera", "sensor_msgs/msg/Image", Image)


def test_jpeg_encodes_and_resizes():
    import cv2

    from fta_agent.codecs.jpeg import JpegCodec

    encoded = JpegCodec(quality=60, max_width=160).encode(make_image_view(320, 240))
    assert encoded.encoding == "jpeg"
    img = cv2.imdecode(np.frombuffer(encoded.data, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[1] == 160  # max_width 리사이즈
    assert img.shape[0] == 120  # 종횡비 유지


def test_jpeg_quality_affects_size():
    from fta_agent.codecs.jpeg import JpegCodec

    view = make_image_view()
    high = JpegCodec(quality=95).encode(view)
    low = JpegCodec(quality=20).encode(view)
    assert len(low.data) < len(high.data)


def test_jpeg_rejects_unknown_encoding():
    from sensor_msgs.msg import Image

    from fta_agent.codecs.jpeg import JpegCodec

    msg = Image()
    msg.height = msg.width = 4
    msg.encoding = "32FC1"
    msg.data = bytes(4 * 4 * 4)
    raw = rclpy_serialization.serialize_message(msg)
    view = MessageView(raw, "/depth", "sensor_msgs/msg/Image", Image)
    with pytest.raises(ValueError, match="32FC1"):
        JpegCodec().encode(view)


def test_voxel_zstd_downsamples():
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py import point_cloud2
    from std_msgs.msg import Header

    from fta_agent.codecs.voxel_zstd import VoxelZstdCodec

    # 0.05m 간격 100점 — 0.5m 복셀이면 크게 줄어야 함
    points = [(i * 0.05, 0.0, 0.0) for i in range(100)]
    cloud = point_cloud2.create_cloud_xyz32(Header(frame_id="lidar"), points)
    raw = rclpy_serialization.serialize_message(cloud)
    view = MessageView(raw, "/lidar", "sensor_msgs/msg/PointCloud2", PointCloud2)

    encoded = VoxelZstdCodec(voxel_size=0.5).encode(view)
    assert encoded.encoding == "voxel_zstd"
    meta = cbor2.loads(zstandard.ZstdDecompressor().decompress(encoded.data))
    assert meta["format"] == "xyz_f32"
    assert meta["count"] == 10  # 5m 범위 / 0.5m 복셀
    pts = np.frombuffer(meta["data"], np.float32).reshape(-1, 3)
    assert len(pts) == meta["count"]
