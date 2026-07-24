"""파이프라인 내부에서 전달되는 메시지 뷰.

구독 콜백은 raw CDR bytes만 담아 즉시 반환한다 (아키텍처 불변 조건 3).
역직렬화가 필요한 컴포넌트(cbor 코덱, M2 deadband 샘플러 등)만
worker 스레드에서 ros_msg()를 호출해 지연 역직렬화한다.
"""
from __future__ import annotations

import time
from typing import Any, Optional, Tuple


class MessageView:
    def __init__(self, raw: bytes, topic: str, msg_type: str, msg_class: Any = None):
        self.raw = raw
        self.topic = topic
        self.msg_type = msg_type          # 예: "nav_msgs/msg/Odometry"
        self.recv_time = time.time()
        self._msg_class = msg_class       # rosidl 메시지 클래스 (없으면 역직렬화 불가)
        self._msg: Any = None

    def ros_msg(self) -> Any:
        """raw CDR을 ROS 메시지로 지연 역직렬화 (worker 스레드 전용)."""
        if self._msg is None:
            if self._msg_class is None:
                raise RuntimeError(
                    f"{self.msg_type} 타입 클래스가 없어 역직렬화할 수 없습니다"
                )
            from rclpy.serialization import deserialize_message

            self._msg = deserialize_message(self.raw, self._msg_class)
        return self._msg

    def ros_stamp(self) -> Optional[Tuple[int, int]]:
        """header.stamp이 있으면 (sec, nanosec) 반환, 없으면 None."""
        try:
            stamp = self.ros_msg().header.stamp
            return (stamp.sec, stamp.nanosec)
        except (AttributeError, RuntimeError):
            return None
