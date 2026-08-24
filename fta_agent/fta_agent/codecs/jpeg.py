"""jpeg 코덱 — sensor_msgs/Image(또는 CompressedImage)를 JPEG 재인코딩 (FR-3.2).

품질(quality)·최대 폭(max_width) 설정 가능. 인코딩은 worker 스레드에서
수행되며 OpenCV는 GIL을 해제하므로 콜백/executor에 영향 없다.
"""
from __future__ import annotations

import cv2
import numpy as np

from fta_agent.codecs.base import EncodedPayload, ICodec
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import CODEC_REGISTRY

# sensor_msgs/Image.encoding → (numpy dtype, 채널 수, BGR 변환 코드)
_CONVERSIONS = {
    "rgb8": (np.uint8, 3, cv2.COLOR_RGB2BGR),
    "bgr8": (np.uint8, 3, None),
    "rgba8": (np.uint8, 4, cv2.COLOR_RGBA2BGR),
    "bgra8": (np.uint8, 4, cv2.COLOR_BGRA2BGR),
    "mono8": (np.uint8, 1, None),
}

# 깊이 이미지(16UC1: mm 정수 / 32FC1: m 실수)의 표시용 범위 — 이 구간을 mono8 로 매핑.
# 프레임별 min-max 정규화는 화면 밝기가 프레임마다 출렁이므로 고정 범위를 쓴다(표시 일관성).
_DEPTH_RANGE_M = (0.3, 10.0)


def _depth_to_mono8(img: "np.ndarray", encoding: str) -> "np.ndarray":
    """깊이 → 표시용 mono8. 가까울수록 밝게, 무측정(0/NaN)은 검정."""
    lo, hi = _DEPTH_RANGE_M
    if encoding == "16UC1":
        meters = img.astype(np.float32) / 1000.0
    else:  # 32FC1
        meters = np.nan_to_num(img.astype(np.float32), nan=0.0)
    valid = meters > 0
    norm = np.clip((hi - meters) / (hi - lo), 0.0, 1.0)  # 가까움=1(밝음)
    out = (norm * 255.0).astype(np.uint8)
    out[~valid] = 0
    return out


@CODEC_REGISTRY.register("jpeg")
class JpegCodec(ICodec):
    def __init__(self, quality: int = 60, max_width: int = 0):
        if not 1 <= int(quality) <= 100:
            raise ValueError(f"jpeg quality는 1~100 (입력: {quality!r})")
        if int(max_width) < 0:
            raise ValueError(f"max_width는 0(제한 없음) 이상 (입력: {max_width!r})")
        self._quality = int(quality)
        self._max_width = int(max_width)

    def encode(self, msg: MessageView) -> EncodedPayload:
        m = msg.ros_msg()
        if hasattr(m, "format"):  # sensor_msgs/CompressedImage
            img = cv2.imdecode(np.frombuffer(bytes(m.data), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"CompressedImage 디코딩 실패 (format={m.format!r})")
        else:  # sensor_msgs/Image
            if m.encoding in ("16UC1", "32FC1"):
                # 깊이 이미지 — 표시용 밝기 맵으로 변환해 JPEG (원본 깊이값 보존은 목적 아님)
                dtype = np.uint16 if m.encoding == "16UC1" else np.float32
                raw = np.frombuffer(bytes(m.data), dtype=dtype).reshape(m.height, m.width)
                return self._finish(_depth_to_mono8(raw, m.encoding))
            if m.encoding not in _CONVERSIONS:
                raise ValueError(
                    f"미지원 이미지 인코딩 '{m.encoding}' "
                    f"(지원: {sorted(_CONVERSIONS) + ['16UC1', '32FC1']})"
                )
            dtype, channels, cvt = _CONVERSIONS[m.encoding]
            img = np.frombuffer(bytes(m.data), dtype).reshape(m.height, m.width, channels)
            if channels == 1:
                img = img[:, :, 0]
            elif cvt is not None:
                img = cv2.cvtColor(img, cvt)

        return self._finish(img)

    def _finish(self, img: "np.ndarray") -> EncodedPayload:
        """공통 마무리 — 리사이즈 + JPEG 인코딩."""
        if self._max_width and img.shape[1] > self._max_width:
            scale = self._max_width / img.shape[1]
            img = cv2.resize(img, (self._max_width, int(img.shape[0] * scale)))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if not ok:
            raise ValueError("JPEG 인코딩 실패")
        return EncodedPayload(data=buf.tobytes(), encoding="jpeg")
