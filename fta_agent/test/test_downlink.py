"""다운링크 검증 체인 단위 테스트 (NFR-7.5 — 4종 거부 + 실행 + 멱등성).

CommandExecutor._handle을 동기 호출한다 (워커 스레드 미사용).
rclpy typesupport(geometry_msgs)가 필요하다.
"""
import json
import time

import pytest

pytest.importorskip("rclpy")

from fta_agent.downlink.audit import AuditLog
from fta_agent.downlink.command_executor import CommandExecutor
from fta_agent.downlink.registry_sync import RegistrySyncManager
from fta_agent.transports.base import ConnState, ITransport, Reliability


class FakeTransport(ITransport):
    def __init__(self):
        self.published = []      # (msg_class, pipeline, dict)
        self.subscriptions = []

    def connect(self):
        pass

    def publish(self, msg_class, pipeline, data, reliability):
        self.published.append((msg_class, pipeline, json.loads(data)))
        return True

    def subscribe(self, topic, callback):
        self.subscriptions.append((topic, callback))

    def state(self):
        return ConnState.CONNECTED

    def close(self):
        pass


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class FakeNode:
    def __init__(self):
        self.pub = FakePublisher()

    def create_publisher(self, msg_type, target, qos):
        return self.pub

    def create_client(self, srv_type, target):
        raise AssertionError("이 테스트에서 서비스 호출은 없어야 함")


SET_GOAL_ENTRY = {
    "interface_id": "set_goal",
    "name": "목적지 설정",
    "kind": "topic",
    "ros_type": "geometry_msgs/msg/PoseStamped",
    "target": "/goal_pose",
    "qos": {"reliability": "reliable", "depth": 1},
    "permission_level": "L2",
    "default_ttl_sec": 30,
    "version": 1,
    "schema": {
        "type": "object",
        "required": ["pose"],
        "properties": {
            "pose": {
                "type": "object",
                "required": ["position"],
                "properties": {"position": {"type": "object", "required": ["x", "y"]}},
            }
        },
    },
}


@pytest.fixture
def setup(tmp_path):
    transport = FakeTransport()
    registry = RegistrySyncManager(transport, "r01")
    registry._active = {"set_goal": SET_GOAL_ENTRY}  # 동기화 완료 상태 주입
    audit = AuditLog(tmp_path / "audit.jsonl")
    node = FakeNode()
    ex = CommandExecutor(
        node=node, transport=transport, registry=registry, audit=audit, robot_id="r01"
    )
    return ex, transport, node, tmp_path


def make_cmd(cmd_id="c1", interface_id="set_goal", ttl=20, issued_offset=0.0, payload=None):
    return json.dumps(
        {
            "cmd_id": cmd_id,
            "interface_id": interface_id,
            "issued_at": time.time() + issued_offset,
            "ttl": ttl,
            "issuer": "tester",
            "payload": payload
            if payload is not None
            else {"pose": {"position": {"x": 1.0, "y": 2.0}}},
        }
    ).encode()


def last_result(transport):
    results = [p for p in transport.published if p[0] == "cmd_result"]
    return results[-1][2] if results else None


def test_valid_topic_command_executes(setup):
    ex, transport, node, _ = setup
    ex._handle(make_cmd(), time.time())
    r = last_result(transport)
    assert r["status"] == "accepted"
    assert len(node.pub.messages) == 1
    assert node.pub.messages[0].pose.position.x == 1.0


def test_unregistered_interface_rejected(setup):
    ex, transport, node, _ = setup
    ex._handle(make_cmd(interface_id="no_such"), time.time())
    r = last_result(transport)
    assert r["status"] == "rejected" and "미등록" in r["detail"]
    assert node.pub.messages == []  # 실행 안 됨


def test_schema_violation_rejected(setup):
    ex, transport, node, _ = setup
    ex._handle(make_cmd(payload={"pose": {"position": {"x": 1.0}}}), time.time())  # y 누락
    r = last_result(transport)
    assert r["status"] == "rejected" and "스키마" in r["detail"]
    assert node.pub.messages == []


def test_missing_ttl_rejected(setup):
    ex, transport, node, _ = setup
    cmd = json.loads(make_cmd())
    del cmd["ttl"]
    ex._handle(json.dumps(cmd).encode(), time.time())
    r = last_result(transport)
    assert r["status"] == "rejected" and "누락" in r["detail"]
    assert node.pub.messages == []


def test_ttl_exceeding_default_rejected(setup):
    ex, transport, node, _ = setup
    ex._handle(make_cmd(ttl=999), time.time())  # default_ttl_sec=30 초과
    r = last_result(transport)
    assert r["status"] == "rejected" and "초과" in r["detail"]
    assert node.pub.messages == []


def test_expired_never_executes(setup):
    """NFR-7.1: 만료 명령의 지연 실행은 어떤 경우에도 금지."""
    ex, transport, node, _ = setup
    ex._handle(make_cmd(ttl=10, issued_offset=-60), time.time())  # 60초 전 발행
    r = last_result(transport)
    assert r["status"] == "expired"
    assert node.pub.messages == []


def test_duplicate_cmd_id_executes_once(setup):
    """NFR-7.2: 동일 cmd_id는 정확히 1회 실행, 중복은 기존 결과 재응답."""
    ex, transport, node, _ = setup
    ex._handle(make_cmd(cmd_id="dup1"), time.time())
    ex._handle(make_cmd(cmd_id="dup1"), time.time())
    assert len(node.pub.messages) == 1  # 1회만 실행
    results = [p[2] for p in transport.published if p[0] == "cmd_result"]
    assert len(results) == 2
    assert results[1]["status"] == "accepted" and "duplicate" in results[1]["detail"]


def test_envelope_missing_fields_rejected(setup):
    ex, transport, node, _ = setup
    ex._handle(json.dumps({"cmd_id": "x", "interface_id": "set_goal"}).encode(), time.time())
    r = last_result(transport)
    assert r["status"] == "rejected"
    assert node.pub.messages == []


def test_audit_log_records_all_stages(setup):
    ex, transport, node, tmp_path = setup
    ex._handle(make_cmd(cmd_id="a1"), time.time())
    ex._handle(make_cmd(cmd_id="a1"), time.time())  # duplicate
    lines = [json.loads(l) for l in open(tmp_path / "audit.jsonl")]
    stages = [l["stage"] for l in lines]
    assert stages == ["received", "accepted", "received", "duplicate"]


# --- RegistrySyncManager ---

def test_registry_sync_supported_and_unsupported():
    transport = FakeTransport()
    sync = RegistrySyncManager(transport, "r01")
    doc = {
        "version": 7,
        "interfaces": [
            SET_GOAL_ENTRY,
            {**SET_GOAL_ENTRY, "interface_id": "bad_type",
             "ros_type": "hunter_msgs/msg/HunterMotorState"},   # typesupport 없음
            {**SET_GOAL_ENTRY, "interface_id": "bad_level", "permission_level": "L9"},
            {**SET_GOAL_ENTRY, "interface_id": "bad_kind", "kind": "action"},
        ],
    }
    sync._on_registry("fleet/registry", json.dumps(doc).encode())
    snap = sync.snapshot()
    assert snap["version"] == 7
    assert snap["supported"] == ["set_goal"]
    assert set(snap["unsupported"]) == {"bad_type", "bad_level", "bad_kind"}
    # registry_status 보고 발행 확인 (FR-9.3)
    status = [p for p in transport.published if p[1] == "registry_status"]
    assert status and status[-1][2]["supported"] == ["set_goal"]


def test_registry_malformed_keeps_previous_state():
    transport = FakeTransport()
    sync = RegistrySyncManager(transport, "r01")
    sync._on_registry("fleet/registry", json.dumps(
        {"version": 1, "interfaces": [SET_GOAL_ENTRY]}).encode())
    sync._on_registry("fleet/registry", b"not json {{{")
    assert sync.get_interface("set_goal") is not None  # 기존 상태 유지
