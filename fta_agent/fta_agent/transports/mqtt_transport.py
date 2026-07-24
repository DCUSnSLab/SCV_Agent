"""MqttTransport — MQTT v5 (paho-mqtt 2.x) 기반 v1 기본 전송 (02 문서 §3.7).

토픽 네임스페이스:
  fleet/{robot_id}/state/{pipeline}   QoS 0
  fleet/{robot_id}/event/{pipeline}   QoS 1
  fleet/{robot_id}/bulk/{pipeline}    QoS 0
  fleet/{robot_id}/sys/lwt            QoS 1 (Last Will)

인증 정보는 환경변수(FTA_MQTT_USERNAME / FTA_MQTT_PASSWORD)로만 주입한다
(불변 조건 6). 재연결은 paho 내장 자동 재연결 사용 — 백오프 파라미터
정교화는 M4에서 다룬다.
"""
from __future__ import annotations

import logging
import os

import paho.mqtt.client as mqtt

from fta_agent.core.registry import TRANSPORT_REGISTRY
from fta_agent.transports.base import ConnState, ITransport, Reliability

logger = logging.getLogger(__name__)


@TRANSPORT_REGISTRY.register("mqtt")
class MqttTransport(ITransport):
    def __init__(
        self,
        robot_id: str,
        host: str,
        port: int = 1883,
        tls: bool = False,
        keepalive_sec: int = 30,
        client_id: str = "",
    ):
        self._robot_id = robot_id
        self._host = host
        self._port = port
        self._keepalive = keepalive_sec
        self._state = ConnState.DISCONNECTED

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or f"fta-{robot_id}",
            protocol=mqtt.MQTTv5,
        )
        username = os.environ.get("FTA_MQTT_USERNAME")
        if username:
            self._client.username_pw_set(username, os.environ.get("FTA_MQTT_PASSWORD"))
        if tls:
            self._client.tls_set()

        self._client.will_set(
            f"fleet/{robot_id}/sys/lwt", payload=robot_id.encode(), qos=1, retain=False
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def connect(self) -> None:
        self._state = ConnState.CONNECTING
        # connect_async + loop_start: 브로커 부재 상태로 기동해도 블로킹 없이
        # 백그라운드에서 접속·재접속을 계속 시도한다 (불변 조건 5)
        self._client.connect_async(self._host, self._port, keepalive=self._keepalive)
        self._client.loop_start()

    def publish(
        self, msg_class: str, pipeline: str, data: bytes, reliability: Reliability
    ) -> bool:
        if self._state is not ConnState.CONNECTED:
            return False
        topic = f"fleet/{self._robot_id}/{msg_class}/{pipeline}"
        info = self._client.publish(topic, data, qos=reliability.value)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def state(self) -> ConnState:
        return self._state

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self._state = ConnState.DISCONNECTED

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.warning("MQTT 접속 거부: %s", reason_code)
            self._state = ConnState.CONNECTING
        else:
            logger.info("MQTT 접속됨: %s:%s", self._host, self._port)
            self._state = ConnState.CONNECTED

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("MQTT 단절 (정상 상황으로 처리, 자동 재접속): %s", reason_code)
        self._state = ConnState.CONNECTING
