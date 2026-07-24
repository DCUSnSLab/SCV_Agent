"""voxel_zstd 코덱 — PointCloud2 복셀 다운샘플 + zstd (FR-3.2).

복셀 그리드로 좌표를 양자화해 복셀당 1점만 남기고, float32 xyz 배열을
CBOR 메타데이터와 함께 zstd 압축한다. 수신측 디코딩:
  zstd 해제 → CBOR → {voxel_size, count, format: "xyz_f32", data}
"""
from __future__ import annotations

import cbor2
import numpy as np
import zstandard
from sensor_msgs_py import point_cloud2

from fta_agent.codecs.base import EncodedPayload, ICodec
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import CODEC_REGISTRY


@CODEC_REGISTRY.register("voxel_zstd")
class VoxelZstdCodec(ICodec):
    def __init__(self, voxel_size: float = 0.2, level: int = 3):
        if not isinstance(voxel_size, (int, float)) or voxel_size <= 0:
            raise ValueError(f"voxel_size는 양수여야 합니다 (입력: {voxel_size!r})")
        self._voxel = float(voxel_size)
        self._compressor = zstandard.ZstdCompressor(level=int(level))

    def encode(self, msg: MessageView) -> EncodedPayload:
        cloud = msg.ros_msg()
        # read_points(구조화 배열) 사용 — read_points_numpy는 intensity/ring 등
        # 혼합 dtype 필드를 가진 클라우드(Velodyne 등)에서 assert로 실패한다
        arr = point_cloud2.read_points(
            cloud, field_names=("x", "y", "z"), skip_nans=True
        )
        pts = np.stack(
            [arr["x"], arr["y"], arr["z"]], axis=-1
        ).astype(np.float32) if len(arr) else np.empty((0, 3), np.float32)

        if len(pts):
            # 복셀 인덱스로 양자화 → 복셀당 첫 점만 유지
            voxel_idx = np.floor(pts / self._voxel).astype(np.int64)
            _, unique_rows = np.unique(voxel_idx, axis=0, return_index=True)
            pts = pts[np.sort(unique_rows)]

        body = cbor2.dumps(
            {
                "voxel_size": self._voxel,
                "count": int(len(pts)),
                "format": "xyz_f32",
                "data": pts.tobytes(),
            }
        )
        return EncodedPayload(data=self._compressor.compress(body), encoding="voxel_zstd")
