"""gps_shim 투영 규율 — 조용히 틀린 위치를 내는 것이 이 함수의 유일한 실패 양상이다.

지도에 찍힌 좌표는 틀려도 '그럴듯해' 보이므로 눈으로는 검출되지 않는다.
거리·방향·차량 분리를 수치로 고정한다.
"""
import math

from fta_tools.gps_shim import project

ORIGIN = (35.9000, 128.8000)
# 위도 1도 ≈ 111.32 km, 경도 1도 ≈ 111.32 km × cos(위도)
_M_PER_DEG_LAT = 111_319.49
_M_PER_DEG_LON = _M_PER_DEG_LAT * math.cos(math.radians(ORIGIN[0]))


def _offset_m(lat, lon):
    """원점 기준 (동쪽 m, 북쪽 m)."""
    return (lon - ORIGIN[1]) * _M_PER_DEG_LON, (lat - ORIGIN[0]) * _M_PER_DEG_LAT


def test_origin_maps_to_origin():
    lat, lon = project(0.0, 0.0, *ORIGIN)
    assert (lat, lon) == ORIGIN


def test_x_is_east_y_is_north():
    """ROS odom 관례(x=전방/동, y=좌/북)를 좌표축에 그대로 대응시킨다."""
    e, n = _offset_m(*project(100.0, 0.0, *ORIGIN))
    assert abs(e - 100.0) < 0.5 and abs(n) < 0.5

    e, n = _offset_m(*project(0.0, 100.0, *ORIGIN))
    assert abs(e) < 0.5 and abs(n - 100.0) < 0.5


def test_offset_separates_vehicles():
    """같은 궤적을 재생하는 두 컨테이너가 지도상 겹치지 않아야 한다 (r01 vs r02 배치)."""
    a = project(0.0, 0.0, *ORIGIN)
    b = project(0.0, 0.0, *ORIGIN, offset_e=150.0, offset_n=-100.0)
    e, n = _offset_m(*b)
    assert abs(e - 150.0) < 0.5 and abs(n + 100.0) < 0.5
    assert a != b


def test_heading_rotates_clockwise():
    """heading 90° 는 동쪽(x+)을 남쪽으로 돌린다 — 두 차량의 궤적 모양을 다르게 만든다."""
    e, n = _offset_m(*project(100.0, 0.0, *ORIGIN, heading_deg=90.0))
    assert abs(e) < 0.5 and abs(n + 100.0) < 0.5


def test_distance_preserved_under_rotation():
    """회전은 원점으로부터의 거리를 바꾸지 않는다."""
    for deg in (0.0, 37.0, 90.0, 213.0):
        e, n = _offset_m(*project(30.0, -40.0, *ORIGIN, heading_deg=deg))
        assert abs(math.hypot(e, n) - 50.0) < 0.5  # 3-4-5 삼각형


def test_real_trajectory_extent_matches_odometry():
    """실측 bag(rosbag2_2026_01_21) 오도메트리 범위 X -40.2~22.0 / Y -56.8~36.2 m 를
    투영해도 같은 범위여야 한다 — 투영이 스케일을 왜곡하면 여기서 걸린다."""
    corners = [(-40.2, -56.8), (22.0, 36.2)]
    pts = [_offset_m(*project(x, y, *ORIGIN)) for x, y in corners]
    assert abs((pts[1][0] - pts[0][0]) - 62.2) < 0.5   # X 폭
    assert abs((pts[1][1] - pts[0][1]) - 93.0) < 0.5   # Y 폭
