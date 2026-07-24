"""JsonMessageConverter — rosidl introspection 기반 JSON ↔ ROS 메시지 (FR-9.5, D7).

서버/웹은 JSON만 다루고, 타입 구조 해석은 전적으로 에이전트가 수행한다.
로컬에 typesupport가 설치된 타입이면 커스텀 타입도 타입별 코드 없이 동작한다.
"""
from __future__ import annotations

from typing import Any, Dict

from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
from rosidl_runtime_py.utilities import get_message, get_service


class ConversionError(Exception):
    pass


def json_to_message(ros_type: str, payload: Dict[str, Any]):
    """JSON dict → ROS 메시지 인스턴스 (kind=topic 용)."""
    try:
        msg = get_message(ros_type)()
    except (AttributeError, ModuleNotFoundError, ValueError) as e:
        raise ConversionError(f"typesupport 없음: {ros_type} ({e})") from e
    try:
        set_message_fields(msg, payload)
    except (AttributeError, TypeError, ValueError, KeyError) as e:
        raise ConversionError(f"JSON→{ros_type} 변환 실패: {e}") from e
    return msg


def json_to_service_request(ros_type: str, payload: Dict[str, Any]):
    """JSON dict → 서비스 Request 인스턴스 (kind=service 용)."""
    try:
        srv = get_service(ros_type)
    except (AttributeError, ModuleNotFoundError, ValueError) as e:
        raise ConversionError(f"typesupport 없음: {ros_type} ({e})") from e
    request = srv.Request()
    try:
        set_message_fields(request, payload)
    except (AttributeError, TypeError, ValueError, KeyError) as e:
        raise ConversionError(f"JSON→{ros_type}.Request 변환 실패: {e}") from e
    return request


def message_to_json(msg) -> Dict[str, Any]:
    """ROS 메시지 → JSON 호환 dict (서비스 응답 반환용)."""
    return message_to_ordereddict(msg)
