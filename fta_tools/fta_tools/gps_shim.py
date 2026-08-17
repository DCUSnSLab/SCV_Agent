"""GpsShim — 로컬 오도메트리를 NavSatFix 로 투영하는 개발용 노드 (가상 차량 전용).

⚠️ **테스트 도구다.** FTA 본체(`fta_agent`)는 로봇 데이터를 가공하지 않는다(02 문서 §1-3).
이 합성은 오직 "가상 차량" 컨테이너 경계 안에서만 일어나며, 서버·웹은 실차와 **완전히
동일한 경로**를 탄다 — 서버가 없는 위치를 지어내는 구조가 아니다.

존재 이유: 보유 rosbag 전량(6종 506GB)에 `sensor_msgs/msg/NavSatFix` 가 0건이다. 실차에는
GPS 가 달리지만 이 주행들은 GPS 없이 기록됐다. 지도 기반 관제 화면을 개발하려면 위치가
필요하므로, 로컬 오도메트리(`odom_bae` 프레임, 단위 m)를 원점 위경도에 얹어 되쏜다.

투영: 정거원통(equirectangular) 근사. 원점에서 수백 m 범위에서 오차가 무시 가능하며
(실측 궤적은 60×90 m), pyproj 등 추가 의존을 들이지 않는다. 넓은 영역이 필요해지면
그때 정식 투영으로 교체할 것.

차량 구분: `offset_east_m`/`offset_north_m`/`heading_offset_deg` 로 같은 bag 을 재생하는
여러 컨테이너를 지도상 서로 다른 위치·방향에 배치한다.

    ros2 run fta_tools gps_shim --ros-args \
        -p origin_lat:=35.9000 -p origin_lon:=128.8000 -p offset_east_m:=150.0
"""
from __future__ import annotations

import math

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles
from sensor_msgs.msg import NavSatFix, NavSatStatus

_EARTH_R = 6378137.0  # WGS84 장반경 (m)


def project(
    x: float,
    y: float,
    origin_lat: float,
    origin_lon: float,
    offset_e: float = 0.0,
    offset_n: float = 0.0,
    heading_deg: float = 0.0,
) -> tuple[float, float]:
    """로컬 (x, y) m → (lat, lon) 도. 순수 함수 — 유닛테스트 대상.

    ROS 관례상 odom 프레임은 x=전방, y=좌측인 ENU 계열이라 (x, y)를 (east, north)로 본다.
    heading_deg 는 궤적 전체를 원점 기준 시계방향으로 회전시킨다(차량별 차별화용).
    """
    if heading_deg:
        r = math.radians(heading_deg)
        cos_r, sin_r = math.cos(r), math.sin(r)
        x, y = x * cos_r + y * sin_r, -x * sin_r + y * cos_r
    east = x + offset_e
    north = y + offset_n
    lat = origin_lat + math.degrees(north / _EARTH_R)
    lon = origin_lon + math.degrees(east / (_EARTH_R * math.cos(math.radians(origin_lat))))
    return lat, lon


class GpsShim(Node):
    def __init__(self) -> None:
        super().__init__("fta_gps_shim")
        self.declare_parameter("odom_topic", "/odom_bae")
        self.declare_parameter("fix_topic", "/gps/fix")
        # 기본 원점은 **임시 가상 좌표**다 — GPS 포함 bag 확보 시 교체한다.
        self.declare_parameter("origin_lat", 35.9000)
        self.declare_parameter("origin_lon", 128.8000)
        self.declare_parameter("offset_east_m", 0.0)
        self.declare_parameter("offset_north_m", 0.0)
        self.declare_parameter("heading_offset_deg", 0.0)
        self.declare_parameter("publish_hz", 5.0)  # odom 은 50Hz — 그대로 되쏘지 않는다

        p = self.get_parameter
        self._origin = (p("origin_lat").value, p("origin_lon").value)
        self._offset = (p("offset_east_m").value, p("offset_north_m").value)
        self._heading = p("heading_offset_deg").value
        hz = p("publish_hz").value
        self._min_interval_ns = int(1e9 / hz) if hz > 0 else 0
        self._last_ns = 0
        self._count = 0

        fix_topic = p("fix_topic").value
        odom_topic = p("odom_topic").value
        # 센서 스트림이므로 best-effort — FTA 구독 기본값(불변 조건 4)과 맞춘다.
        qos = QoSPresetProfiles.SENSOR_DATA.value
        self._pub = self.create_publisher(NavSatFix, fix_topic, qos)
        self.create_subscription(Odometry, odom_topic, self._on_odom, qos)
        self.get_logger().info(
            f"GpsShim: {odom_topic} → {fix_topic} @{hz}Hz | "
            f"원점=({self._origin[0]:.6f}, {self._origin[1]:.6f}) "
            f"오프셋=({self._offset[0]}, {self._offset[1]})m 회전={self._heading}°"
        )

    def _on_odom(self, msg: Odometry) -> None:
        now_ns = self.get_clock().now().nanoseconds
        if self._min_interval_ns and now_ns - self._last_ns < self._min_interval_ns:
            return
        self._last_ns = now_ns

        pos = msg.pose.pose.position
        lat, lon = project(
            pos.x, pos.y, self._origin[0], self._origin[1],
            self._offset[0], self._offset[1], self._heading,
        )

        fix = NavSatFix()
        fix.header.stamp = msg.header.stamp  # 원 오도메트리 시각 보존 (지연 측정 근거)
        fix.header.frame_id = "gps"
        fix.status.status = NavSatStatus.STATUS_FIX
        fix.status.service = NavSatStatus.SERVICE_GPS
        fix.latitude = lat
        fix.longitude = lon
        fix.altitude = float(pos.z)
        fix.position_covariance_type = NavSatFix.COVARIANCE_TYPE_UNKNOWN
        self._pub.publish(fix)

        self._count += 1
        if self._count % 200 == 0:
            self.get_logger().info(f"GpsShim {self._count}건 — 최근 ({lat:.6f}, {lon:.6f})")


def main(argv=None) -> int:
    rclpy.init(args=argv)
    node = GpsShim()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0
