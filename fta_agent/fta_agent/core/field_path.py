"""점(.) 구분 필드 경로로 ROS 메시지 필드에 접근하는 헬퍼.

deadband/event 샘플러가 설정의 ``field: pose.pose.position.x`` 값을
런타임에 해석할 때 사용한다. 배열 인덱스는 ``ranges[0]`` 형태를 지원한다.
"""
from __future__ import annotations

import re
from typing import Any

_INDEX_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]$")


class FieldPathError(Exception):
    pass


def as_number(value: Any, path: str = "") -> Any:
    """수치 비교용으로 필드 값을 정규화한다.

    rclpy는 ROS의 ``octet``/``uint8`` 필드를 길이 1의 ``bytes``로 노출한다
    (예: ``DiagnosticStatus.level``). 그대로 int와 비교하면 TypeError가 나므로
    단일 바이트는 정수로 바꿔준다. 그 외 타입은 손대지 않는다.
    """
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 1:
            raise TypeError(
                f"필드 '{path}'는 길이 {len(value)}의 바이트열이라 수치 비교할 수 없습니다"
            )
        return value[0]
    return value


def get_field(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        m = _INDEX_PATTERN.match(part)
        try:
            if m:
                current = getattr(current, m.group(1))[int(m.group(2))]
            else:
                current = getattr(current, part)
        except (AttributeError, IndexError, TypeError) as e:
            raise FieldPathError(
                f"필드 경로 '{path}' 해석 실패 ('{part}' 단계): {e}"
            ) from e
    return current
