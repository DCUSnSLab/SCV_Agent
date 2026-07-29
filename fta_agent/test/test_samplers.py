"""샘플러 단위 테스트 — ROS 비의존 (가짜 MessageView 사용)."""
from types import SimpleNamespace

import pytest

from fta_agent.core.field_path import FieldPathError, get_field
from fta_agent.samplers.base import Decision
from fta_agent.samplers.deadband import DeadbandSampler
from fta_agent.samplers.event import EventSampler
from fta_agent.samplers.on_demand import OnDemandSampler
from fta_agent.samplers.rate import RateSampler


class FakeView:
    """MessageView 대역 — ros_msg()만 흉내낸다."""

    def __init__(self, **fields):
        self._msg = SimpleNamespace(**fields)

    def ros_msg(self):
        return self._msg


def ns(**kw):
    return SimpleNamespace(**kw)


# --- field_path ---

def test_get_field_nested():
    obj = ns(pose=ns(position=ns(x=1.5)))
    assert get_field(obj, "pose.position.x") == 1.5


def test_get_field_index():
    obj = ns(status=[ns(level=2)])
    assert get_field(obj, "status[0].level") == 2


def test_get_field_missing_raises():
    with pytest.raises(FieldPathError, match="nope"):
        get_field(ns(a=1), "nope.x")


# --- rate ---

def test_rate_downsamples_to_target_hz():
    s = RateSampler(hz=2)  # 0.5s 간격
    decisions = [s.decide(FakeView(), t / 100.0) for t in range(0, 300, 2)]  # 50Hz, 3초
    passed = decisions.count(Decision.PASS)
    assert passed == 6  # 3초 × 2Hz (t=0 포함, 이후 0.5s마다)


def test_rate_rejects_invalid_hz():
    with pytest.raises(ValueError):
        RateSampler(hz=0)


# --- deadband ---

def test_deadband_first_message_passes():
    s = DeadbandSampler(field="percentage", threshold=0.005)
    assert s.decide(FakeView(percentage=0.8), 0.0) is Decision.PASS


def test_deadband_blocks_small_changes_passes_large():
    s = DeadbandSampler(field="percentage", threshold=0.005)
    s.decide(FakeView(percentage=0.800), 0.0)
    assert s.decide(FakeView(percentage=0.801), 1.0) is Decision.DROP
    assert s.decide(FakeView(percentage=0.794), 2.0) is Decision.PASS
    # 기준값이 0.794로 갱신되었는지
    assert s.decide(FakeView(percentage=0.793), 3.0) is Decision.DROP


# --- event ---

def test_event_changed_fires_on_change_only():
    s = EventSampler(field="data", condition="changed")
    assert s.decide(FakeView(data=False), 0.0) is Decision.PASS_AND_FLUSH  # 초기 상태
    assert s.decide(FakeView(data=False), 1.0) is Decision.DROP
    assert s.decide(FakeView(data=True), 2.0) is Decision.PASS_AND_FLUSH
    assert s.decide(FakeView(data=True), 3.0) is Decision.DROP
    assert s.decide(FakeView(data=False), 4.0) is Decision.PASS_AND_FLUSH


def test_event_gte_edge_triggered():
    s = EventSampler(field="level", condition="gte", value=1)
    assert s.decide(FakeView(level=0), 0.0) is Decision.PASS_AND_FLUSH  # 초기 상태
    assert s.decide(FakeView(level=0), 1.0) is Decision.DROP
    assert s.decide(FakeView(level=2), 2.0) is Decision.PASS_AND_FLUSH  # 상승 엣지
    assert s.decide(FakeView(level=2), 3.0) is Decision.DROP            # 유지 중 재발화 없음
    assert s.decide(FakeView(level=0), 4.0) is Decision.DROP            # 해제
    assert s.decide(FakeView(level=1), 5.0) is Decision.PASS_AND_FLUSH  # 재발생


def test_event_compares_octet_field_as_number():
    """octet/uint8 필드는 rclpy가 bytes로 노출한다 (예: DiagnosticStatus.level).

    정규화가 없으면 `bytes >= int`에서 TypeError가 나고 해당 메시지가 통째로 폐기된다
    (이슈 A-3 — 실제 종단 검증에서 진단 파이프라인 20건 전량 error 처리됨).
    """
    s = EventSampler(field="level", condition="gte", value=1)
    assert s.decide(FakeView(level=b"\x00"), 0.0) is Decision.PASS_AND_FLUSH  # 초기 상태
    assert s.decide(FakeView(level=b"\x00"), 1.0) is Decision.DROP
    assert s.decide(FakeView(level=b"\x02"), 2.0) is Decision.PASS_AND_FLUSH  # WARN 상승 엣지
    assert s.decide(FakeView(level=b"\x02"), 3.0) is Decision.DROP
    assert s.decide(FakeView(level=b"\x00"), 4.0) is Decision.DROP


def test_event_changed_works_with_octet_field():
    s = EventSampler(field="level", condition="changed")
    assert s.decide(FakeView(level=b"\x00"), 0.0) is Decision.PASS_AND_FLUSH
    assert s.decide(FakeView(level=b"\x00"), 1.0) is Decision.DROP
    assert s.decide(FakeView(level=b"\x01"), 2.0) is Decision.PASS_AND_FLUSH


def test_deadband_accepts_octet_field():
    """deadband도 같은 필드 타입을 만난다 — float() 변환이 bytes에서 실패한다."""
    s = DeadbandSampler(field="level", threshold=1)
    assert s.decide(FakeView(level=b"\x00"), 0.0) is Decision.PASS
    assert s.decide(FakeView(level=b"\x00"), 1.0) is Decision.DROP
    assert s.decide(FakeView(level=b"\x02"), 2.0) is Decision.PASS


def test_event_multibyte_field_is_not_coerced():
    """길이 1이 아닌 bytes는 수치가 아니므로 조용히 넘기지 않고 원인을 밝히며 실패한다."""
    s = EventSampler(field="blob", condition="gte", value=1)
    with pytest.raises(TypeError, match="바이트열"):
        s.decide(FakeView(blob=b"\x00\x01"), 0.0)


def test_event_requires_value_for_comparison():
    with pytest.raises(ValueError, match="value"):
        EventSampler(field="level", condition="gte")


def test_event_unknown_condition():
    with pytest.raises(ValueError, match="condition"):
        EventSampler(field="x", condition="between")


# --- on_demand ---

def test_on_demand_passes_only_when_requested():
    s = OnDemandSampler()
    assert s.decide(FakeView(), 0.0) is Decision.DROP
    s.request()
    assert s.decide(FakeView(), 1.0) is Decision.PASS
    assert s.decide(FakeView(), 2.0) is Decision.DROP


def test_on_demand_multiple_requests():
    s = OnDemandSampler()
    s.request(2)
    assert s.decide(FakeView(), 0.0) is Decision.PASS
    assert s.decide(FakeView(), 1.0) is Decision.PASS
    assert s.decide(FakeView(), 2.0) is Decision.DROP
