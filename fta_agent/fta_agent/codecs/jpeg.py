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
            if m.encoding not in _CONVERSIONS:
                raise ValueError(
                    f"미지원 이미지 인코딩 '{m.encoding}' (지원: {sorted(_CONVERSIONS)})"
                )
            dtype, channels, cvt = _CONVERSIONS[m.encoding]
            img = np.frombuffer(bytes(m.data), dtype).reshape(m.height, m.width, channels)
            if channels == 1:
                img = img[:, :, 0]
            elif cvt is not None:
                img = cv2.cvtColor(img, cvt)

        if self._max_width and img.shape[1] > self._max_width:
            scale = self._max_width / img.shape[1]
            img = cv2.resize(img, (self._max_width, int(img.shape[0] * scale)))

        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if not ok:
            raise ValueError("JPEG 인코딩 실패")
        return EncodedPayload(data=buf.tobytes(), encoding="jpeg")
