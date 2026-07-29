"""UplinkManager 회귀 테스트 — 큐 포화 유실(A-7)·drain 트리거(A-8).

M4 단절 테스트가 지나가지 않는 경로를 재현한다:
  A-7 연결이 정상인데 큐가 포화되어 critical/event가 유실되는 경로
  A-8 연결이 유지된 채 버퍼에 쌓인 데이터가 배출되지 않는 경로
"""
import time
from types import SimpleNamespace

from fta_agent.core.disk_buffer import DiskBuffer
from fta_agent.core.priority_queue import PriorityOutQueue
from fta_agent.core.uplink_manager import UplinkManager
from fta_agent.transports.base import ConnState, ITransport


class FakeTransport(ITransport):
    """발행 성공/실패와 연결 상태를 테스트가 제어하는 전송."""

    def __init__(self, state=ConnState.CONNECTED, ok=True):
        self._state = state
        self.ok = ok
        self.published = []

    def connect(self) -> None:  # pragma: no cover — 인터페이스 충족용
        self._state = ConnState.CONNECTED

    def subscribe(self, topic, callback) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        self._state = ConnState.DISCONNECTED

    def publish(self, msg_class, name, data, reliability) -> bool:
        if not self.ok:
            return False
        self.published.append((msg_class, name, data))
        return True

    def state(self) -> ConnState:
        return self._state

    def set_state(self, state) -> None:
        self._state = state


def _pipeline(name, msg_class):
    return SimpleNamespace(name=name, msg_class=msg_class)


def _wait_for(pred, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


# ---- A-7: 큐 포화 시 critical/event 보존 ----

def test_queue_overflow_preserves_critical_to_buffer(tmp_path):
    """연결 정상 + 큐 포화 → critical은 드롭이 아니라 DiskBuffer로 이관 (02 §3.5)."""
    q = PriorityOutQueue(maxlen_per_priority=2)
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    transport = FakeTransport()
    mgr = UplinkManager(q, transport, disk_buffer=buf)

    estop = _pipeline("estop", "event")
    for i in range(5):  # 용량 2 → 3건이 밀려남
        q.push((estop, f"e{i}".encode()), "critical", conflate_key="estop")

    assert q.dropped["critical"] == 0, "critical은 드롭되지 않아야 한다"
    assert buf.pending()["event_segments"] >= 1, "밀려난 critical은 버퍼에 남아야 한다"

    # 이관분 + 큐 잔여분이 모두 전송되는지 (순서 무관, 전량 도달)
    mgr.start()
    assert _wait_for(lambda: len(transport.published) == 5)
    assert sorted(d for _, _, d in transport.published) == [f"e{i}".encode() for i in range(5)]
    mgr.stop()


def test_queue_overflow_preserves_event_class_at_high_priority(tmp_path):
    """priority가 high여도 msg_class=event면 사건이므로 보존한다."""
    q = PriorityOutQueue(maxlen_per_priority=1)
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    mgr = UplinkManager(q, FakeTransport(), disk_buffer=buf)  # noqa: F841 — 핸들러 등록 목적

    alarm = _pipeline("alarm", "event")
    q.push((alarm, b"a0"), "high", conflate_key="alarm_0")
    q.push((alarm, b"a1"), "high", conflate_key="alarm_1")  # 키가 달라 conflation 불가

    assert q.dropped["high"] == 0
    assert buf.pending()["event_segments"] >= 1


def test_queue_overflow_preserves_event_class_on_conflation(tmp_path):
    """conflation 경로에서도 이벤트는 버려지지 않는다.

    파이프라인은 conflate_key로 자기 이름을 쓰므로, high 우선순위 이벤트 파이프라인이
    포화되면 매번 conflation 경로를 탄다. 최신값 교체는 상태 데이터 전제의 최적화이므로
    이벤트에 적용하면 사건이 소실된다 (종단 재현에서 410건 소실 확인).
    """
    q = PriorityOutQueue(maxlen_per_priority=1)
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    mgr = UplinkManager(q, FakeTransport(), disk_buffer=buf)  # noqa: F841

    alarm = _pipeline("alarm", "event")
    q.push((alarm, b"a0"), "high", conflate_key="alarm")
    q.push((alarm, b"a1"), "high", conflate_key="alarm")  # 같은 키 → conflation 경로

    assert q.conflated["high"] == 0, "이벤트는 최신값으로 덮어쓰면 안 된다"
    assert q.preserved["high"] == 1
    assert buf.pending()["event_segments"] >= 1


def test_state_pipeline_still_conflates(tmp_path):
    """상태 데이터의 conflation(최신값 우선)은 그대로 유지 — 디스크에 쓰지 않는다."""
    q = PriorityOutQueue(maxlen_per_priority=1)
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    mgr = UplinkManager(q, FakeTransport(), disk_buffer=buf)  # noqa: F841

    odom = _pipeline("odom", "state")
    q.push((odom, b"v0"), "high", conflate_key="odom")
    q.push((odom, b"v1"), "high", conflate_key="odom")

    assert q.conflated["high"] == 1
    assert q.preserved["high"] == 0
    assert buf.pending()["event_segments"] == 0
    assert q.pop(timeout=0.1) == ("high", (odom, b"v1"))  # 최신값이 남는다


def test_queue_overflow_still_drops_bulk_and_state(tmp_path):
    """state/bulk까지 디스크로 보내지는 않는다 — 단절 시 정책과 동일."""
    q = PriorityOutQueue(maxlen_per_priority=1)
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    mgr = UplinkManager(q, FakeTransport(), disk_buffer=buf)  # noqa: F841

    cam = _pipeline("cam", "bulk")
    q.push((cam, b"f0"), "low", conflate_key="cam")
    q.push((cam, b"f1"), "low", conflate_key="cam")

    assert q.dropped["low"] == 1
    assert buf.pending()["event_segments"] == 0


def test_queue_overflow_without_buffer_counts_drop():
    """버퍼 미설정(설정에 buffer.dir 없음)이면 기존대로 드롭 집계."""
    q = PriorityOutQueue(maxlen_per_priority=1)
    mgr = UplinkManager(q, FakeTransport(), disk_buffer=None)  # noqa: F841

    estop = _pipeline("estop", "event")
    q.push((estop, b"e0"), "critical", conflate_key="estop")
    q.push((estop, b"e1"), "critical", conflate_key="estop")
    assert q.dropped["critical"] == 1


# ---- A-8: 연결 유지 상태에서도 버퍼 배출 ----

def test_drain_retries_while_connected(tmp_path):
    """재연결 이벤트 없이 연결이 계속 유지돼도 버퍼 잔량은 배출된다."""
    q = PriorityOutQueue()
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    transport = FakeTransport()
    mgr = UplinkManager(q, transport, disk_buffer=buf, drain_retry_sec=0.3)

    mgr.start()
    assert _wait_for(lambda: mgr._was_connected)  # 최초 연결 처리 완료 (엣지 소진)

    # 이후에 버퍼로 들어온 데이터 — 재연결 엣지는 더 이상 발생하지 않는다
    buf.append_event("estop", "event", "critical", b"late")
    assert _wait_for(lambda: any(d == b"late" for _, _, d in transport.published)), \
        "연결 유지 중에도 주기적으로 drain 되어야 한다"
    mgr.stop()


def test_partial_drain_resumes_without_reconnect(tmp_path):
    """drain 중간 실패로 남은 세그먼트도 다음 주기에 이어서 배출된다."""
    q = PriorityOutQueue()
    buf = DiskBuffer(tmp_path, max_disk_mb=10)
    transport = FakeTransport(ok=False)  # 처음엔 발행 실패
    mgr = UplinkManager(q, transport, disk_buffer=buf, drain_retry_sec=0.3)

    for i in range(3):
        buf.append_event("estop", "event", "critical", f"e{i}".encode())

    mgr.start()
    assert _wait_for(lambda: mgr.stats["publish_failed"] >= 0)
    time.sleep(0.5)
    assert transport.published == []

    transport.ok = True  # 발행 가능해짐 — 재연결은 일어나지 않음
    assert _wait_for(lambda: len(transport.published) == 3)
    mgr.stop()
