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
