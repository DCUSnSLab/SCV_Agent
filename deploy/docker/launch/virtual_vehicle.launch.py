"""가상 차량 1대 = 컨테이너 1개 — bag 재생 + GPS shim + FTA 에이전트를 한 launch 로 묶는다.

프로세스 관리를 supervisor/tini 조합 대신 `ros2 launch` 로 하는 이유: ROS 네이티브
프로세스 관리자라 종료 신호 전파·로그 집계가 이미 되어 있고, bag 재생(ExecuteProcess)과
노드(Node)를 같은 수명주기에 둘 수 있다.

기동 순서: 에이전트·shim 을 먼저 올리고 BAG_START_DELAY(기본 5초) 뒤에 bag 을 재생한다 —
구독이 붙기 전에 재생이 시작되면 초반 메시지가 통째로 유실된다.

설정은 전부 환경변수로 (컨테이너 = 설정 차이로만 구분되는 개체):
  ROBOT_ID · FTA_CONFIG · MQTT_HOST
  BAG_PATH · BAG_TOPICS(공백구분) · BAG_RATE · BAG_START_OFFSET · BAG_START_DELAY · BAG_LOOP
  GPS_ORIGIN_LAT · GPS_ORIGIN_LON · GPS_OFFSET_EAST · GPS_OFFSET_NORTH · GPS_HEADING · GPS_HZ
  ODOM_TOPIC · FTA_LOG_LEVEL · FTA_LOG_FORMAT
"""
import os

from launch import LaunchDescription
from launch.actions import ExecuteProcess, TimerAction
from launch_ros.actions import Node


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None or v == "" else v


def generate_launch_description() -> LaunchDescription:
    bag_path = _env("BAG_PATH", "")
    bag_topics = _env("BAG_TOPICS", "").split()
    start_delay = float(_env("BAG_START_DELAY", "5.0"))

    gps_shim = Node(
        package="fta_tools",
        executable="gps_shim",
        name="fta_gps_shim",
        output="screen",
        parameters=[{
            "odom_topic": _env("ODOM_TOPIC", "/odom_bae"),
            "fix_topic": "/gps/fix",
            "origin_lat": float(_env("GPS_ORIGIN_LAT", "35.9000")),
            "origin_lon": float(_env("GPS_ORIGIN_LON", "128.8000")),
            "offset_east_m": float(_env("GPS_OFFSET_EAST", "0.0")),
            "offset_north_m": float(_env("GPS_OFFSET_NORTH", "0.0")),
            "heading_offset_deg": float(_env("GPS_HEADING", "0.0")),
            "publish_hz": float(_env("GPS_HZ", "5.0")),
        }],
    )

    agent = Node(
        package="fta_agent",
        executable="agent",
        name="fta_agent",
        output="screen",
        arguments=[
            "--config", _env("FTA_CONFIG", "/opt/fta/config/r01.yaml"),
            "--log-level", _env("FTA_LOG_LEVEL", "INFO"),
            "--log-format", _env("FTA_LOG_FORMAT", "text"),
        ],
    )

    actions = [gps_shim, agent]

    if bag_path:
        cmd = ["ros2", "bag", "play", bag_path,
               "--rate", _env("BAG_RATE", "1.0"),
               "--start-offset", _env("BAG_START_OFFSET", "0.0")]
        if _env("BAG_LOOP", "1") not in ("0", "false", "False"):
            cmd.append("--loop")
        if bag_topics:
            # 토픽 필터는 storage 레벨에서 걸린다 — 제외한 토픽은 디스크를 아예 안 읽는다.
            # raw Image 가 전체 용량을 지배하므로(56GB 중 ~45GB) 이 필터가 곧 성능이다.
            cmd += ["--topics"] + bag_topics
        actions.append(TimerAction(period=start_delay, actions=[
            ExecuteProcess(cmd=cmd, output="screen", name="bag_play"),
        ]))

    return LaunchDescription(actions)
