"""MqttTransport TLS 설정 전달 테스트 (이슈 A-9).

실제 핸드셰이크는 검증하지 않는다 — 설정 값이 paho의 tls_set에 그대로 전달되는지,
잘못된 조합이 기동 시점에 걸러지는지만 본다. 핸드셰이크 검증은 자체 서명 인증서로
TLS 브로커를 띄우는 별도 통합 테스트 몫이다.
"""
import pytest

from fta_agent.transports import mqtt_transport as mt


class FakeClient:
    def __init__(self, *a, **kw):
        self.tls_kwargs = None
        self.insecure = None
        self.auth = None

    def username_pw_set(self, username, password=None):
        self.auth = (username, password)

    def tls_set(self, **kwargs):
        self.tls_kwargs = kwargs

    def tls_insecure_set(self, value):
        self.insecure = value

    def will_set(self, *a, **kw):
        pass

    def reconnect_delay_set(self, **kw):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    created = {}

    def factory(*a, **kw):
        c = FakeClient()
        created["client"] = c
        return c

    monkeypatch.setattr(mt.mqtt, "Client", factory)
    return created


def test_tls_disabled_does_not_configure_tls(fake_client):
    mt.MqttTransport(robot_id="r01", host="localhost", tls=False)
    assert fake_client["client"].tls_kwargs is None


def test_tls_enabled_uses_system_trust_store_by_default(fake_client):
    """공인 CA 인증서를 쓰는 운영 기본값 — 로봇에 인증서 배포가 필요 없다."""
    mt.MqttTransport(robot_id="r01", host="mqtt.example.com", port=8883, tls=True)
    assert fake_client["client"].tls_kwargs == {
        "ca_certs": None, "certfile": None, "keyfile": None
    }
    assert fake_client["client"].insecure is None


def test_private_ca_and_client_cert_are_passed_through(fake_client):
    mt.MqttTransport(
        robot_id="r01", host="mqtt.example.com", port=8883, tls=True,
        ca_certs="/etc/fta/ca.crt", certfile="/etc/fta/r01.crt", keyfile="/etc/fta/r01.key",
    )
    assert fake_client["client"].tls_kwargs == {
        "ca_certs": "/etc/fta/ca.crt",
        "certfile": "/etc/fta/r01.crt",
        "keyfile": "/etc/fta/r01.key",
    }


def test_certfile_without_keyfile_fails_at_startup(fake_client):
    """조용히 무시하면 mTLS가 안 걸린 채 운영에 나간다 — 기동 시점에 실패시킨다."""
    with pytest.raises(ValueError, match="keyfile"):
        mt.MqttTransport(
            robot_id="r01", host="mqtt.example.com", tls=True, certfile="/etc/fta/r01.crt"
        )


def test_tls_insecure_is_opt_in(fake_client):
    mt.MqttTransport(robot_id="r01", host="10.0.0.5", tls=True, tls_insecure=True)
    assert fake_client["client"].insecure is True
