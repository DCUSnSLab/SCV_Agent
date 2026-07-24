"""CommandExecutor — 다운링크 명령 검증·실행 (FR-9.4~9.7, NFR-7).

⚠️ 안전 조항 (NFR-7.5 — 협상 불가):
검증 체인은 ① 레지스트리 등록 → ② payload 스키마 → ③ TTL → ④ cmd_id 멱등성
순서로 고정이며, 이 체인을 우회하는 실행 경로는 존재해서는 안 된다.
실행은 _validate()가 인터페이스 정의를 반환한 경우에만 도달 가능하다.
어떤 리팩토링에서도 이 구조를 완화하지 말 것 (완화가 아닌 구체화 방향만 허용).

- TTL 없는 명령은 즉시 거부, envelope ttl은 default_ttl_sec 초과 불가 (NFR-7.1)
- 만료 명령은 절대 실행하지 않고 expired 응답 후 폐기 (NFR-7.1)
- 동일 cmd_id는 정확히 1회 실행, 중복 수신 시 기존 결과 재응답 (NFR-7.2)
- 모든 명령은 응답을 갖는다: accepted|done|failed|rejected|expired (FR-9.7)
- 전 과정 감사 로그 (NFR-7.6)
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import OrderedDict
from typing import Optional

import jsonschema

from fta_agent.downlink.audit import AuditLog
from fta_agent.downlink.json_converter import (
    json_to_message,
    json_to_service_request,
    message_to_json,
)
from fta_agent.downlink.registry_sync import RegistrySyncManager
from fta_agent.transports.base import ITransport, Reliability

logger = logging.getLogger(__name__)

ENVELOPE_REQUIRED = ("cmd_id", "interface_id", "issued_at", "ttl", "issuer", "payload")


class CommandExecutor:
    def __init__(
        self,
        node,                       # rclpy Node — 발행자/서비스 클라이언트 생성용
        transport: ITransport,
        registry: RegistrySyncManager,
        audit: AuditLog,
        robot_id: str,
        service_timeout_sec: float = 10.0,
        idempotency_cache_size: int = 1024,
    ):
        self._node = node
        self._transport = transport
        self._registry = registry
        self._audit = audit
        self._robot_id = robot_id
        self._service_timeout = service_timeout_sec
        self._seen: OrderedDict = OrderedDict()  # cmd_id → result (LRU, NFR-7.2)
        self._seen_max = idempotency_cache_size
        self._publishers: dict = {}              # interface_id → (version, publisher)
        self._clients: dict = {}
        self._queue: queue.Queue = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="downlink-exec", daemon=True)

    def start(self) -> None:
        self._transport.subscribe(f"fleet/{self._robot_id}/cmd/+", self._on_command)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._worker.join(timeout=5.0)

    # ---- 수신 (transport 콜백 스레드 — 파싱·큐 적재만) ----

    def _on_command(self, topic: str, payload: bytes) -> None:
        try:
            self._queue.put_nowait((topic, payload, time.time()))
        except queue.Full:
            logger.error("다운링크 명령 큐 포화 — 명령 폐기 (topic=%s)", topic)

    # ---- 실행 워커 ----

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                topic, payload, recv_time = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._handle(payload, recv_time)
            except Exception:
                logger.exception("다운링크 명령 처리 중 예기치 못한 오류")

    def _handle(self, payload: bytes, recv_time: float) -> None:
        try:
            env = json.loads(payload.decode("utf-8"))
            assert isinstance(env, dict)
        except Exception as e:
            # envelope 자체가 파싱 불가 — cmd_id를 알 수 없어도 감사 기록은 남긴다
            self._audit.record(cmd_id=None, interface_id=None, issuer=None,
                               stage="rejected", detail=f"envelope 파싱 실패: {e}")
            return

        cmd_id = env.get("cmd_id")
        interface_id = env.get("interface_id")
        issuer = env.get("issuer")
        self._audit.record(cmd_id=cmd_id, interface_id=interface_id, issuer=issuer,
                           stage="received", detail="")

        missing = [f for f in ENVELOPE_REQUIRED if f not in env]
        if missing:
            self._finish(env, "rejected", f"envelope 필수 필드 누락: {missing}")
            return

        # ---- 검증 체인 (NFR-7.5 — 순서 고정, 우회 금지) ----
        entry = self._validate(env, recv_time)
        if entry is None:
            return  # 각 단계에서 이미 응답·감사 기록 완료

        # ---- 실행 (검증 체인 통과 명령만 도달) ----
        self._execute(env, entry)

    def _validate(self, env: dict, recv_time: float) -> Optional[dict]:
        cmd_id = env["cmd_id"]

        # ① 레지스트리 등록 여부 (FR-9.1: 미등록 대상 실행 불가)
        entry = self._registry.get_interface(env["interface_id"])
        if entry is None:
            self._finish(env, "rejected",
                         f"미등록/미지원 인터페이스: {env['interface_id']}")
            return None

        # ② payload 스키마 (JSON Schema)
        try:
            jsonschema.validate(env["payload"], entry["schema"])
        except jsonschema.ValidationError as e:
            self._finish(env, "rejected", f"payload 스키마 위반: {e.message}")
            return None

        # ③ TTL (NFR-7.1 — TTL 필수, default_ttl 초과 불가, 만료 시 실행 금지)
        ttl = env["ttl"]
        issued_at = env["issued_at"]
        if not isinstance(ttl, (int, float)) or ttl <= 0:
            self._finish(env, "rejected", f"유효하지 않은 ttl: {ttl!r} (NFR-7.1)")
            return None
        if not isinstance(issued_at, (int, float)):
            self._finish(env, "rejected", f"유효하지 않은 issued_at: {issued_at!r}")
            return None
        if ttl > entry["default_ttl_sec"]:
            self._finish(env, "rejected",
                         f"ttl {ttl}s가 인터페이스 default_ttl {entry['default_ttl_sec']}s 초과 (NFR-7.1)")
            return None
        if recv_time > issued_at + ttl:
            self._finish(env, "expired",
                         f"TTL 만료: issued_at+ttl 대비 {recv_time - issued_at - ttl:.1f}s 경과 — 폐기")
            return None

        # ④ 멱등성 (NFR-7.2 — 중복 cmd_id는 재실행 없이 기존 결과 재응답)
        if cmd_id in self._seen:
            cached = self._seen[cmd_id]
            self._audit.record(cmd_id=cmd_id, interface_id=env["interface_id"],
                               issuer=env["issuer"], stage="duplicate",
                               detail=f"기존 결과 재응답: {cached['status']}")
            self._respond(env, cached["status"], cached["detail"] + " (duplicate)")
            return None

        return entry

    def _execute(self, env: dict, entry: dict) -> None:
        if entry["kind"] == "topic":
            self._execute_topic(env, entry)
        else:
            self._execute_service(env, entry)

    def _execute_topic(self, env: dict, entry: dict) -> None:
        try:
            msg = json_to_message(entry["ros_type"], env["payload"])
            pub = self._get_publisher(entry)
            pub.publish(msg)
        except Exception as e:  # 실행 실패(변환 포함)는 failed 응답 (FR-9.7 무응답 금지)
            self._finish(env, "failed", f"topic 발행 실패: {e}")
            return
        self._finish(env, "accepted", f"{entry['target']} 1회 발행")

    def _execute_service(self, env: dict, entry: dict) -> None:
        try:
            request = json_to_service_request(entry["ros_type"], env["payload"])
            client = self._get_client(entry)
            if not client.wait_for_service(timeout_sec=min(2.0, self._service_timeout)):
                self._finish(env, "failed", f"서비스 없음: {entry['target']}")
                return
            future = client.call_async(request)
            done = threading.Event()
            future.add_done_callback(lambda f: done.set())
            if not done.wait(timeout=self._service_timeout):
                future.cancel()
                self._finish(env, "failed", f"서비스 타임아웃 ({self._service_timeout}s)")
                return
            response = future.result()
        except Exception as e:  # 실행 실패(변환 포함)는 failed 응답 (FR-9.7 무응답 금지)
            self._finish(env, "failed", f"service 호출 실패: {e}")
            return
        self._finish(env, "done", json.dumps(message_to_json(response), ensure_ascii=False))

    # ---- 응답·감사 ----

    def _finish(self, env: dict, status: str, detail: str) -> None:
        cmd_id = env.get("cmd_id")
        if cmd_id is not None:
            self._seen[cmd_id] = {"status": status, "detail": detail}
            self._seen.move_to_end(cmd_id)
            while len(self._seen) > self._seen_max:
                self._seen.popitem(last=False)
        self._audit.record(cmd_id=cmd_id, interface_id=env.get("interface_id"),
                           issuer=env.get("issuer"), stage=status, detail=detail)
        self._respond(env, status, detail)

    def _respond(self, env: dict, status: str, detail: str) -> None:
        result = {"cmd_id": env.get("cmd_id"), "status": status, "detail": detail}
        self._transport.publish(
            "cmd_result", env.get("interface_id") or "unknown",
            json.dumps(result, ensure_ascii=False).encode("utf-8"),
            Reliability.AT_LEAST_ONCE,
        )

    # ---- ROS 인터페이스 캐시 (레지스트리 version 변경 시 재생성) ----

    def _get_publisher(self, entry: dict):
        key = entry["interface_id"]
        cached = self._publishers.get(key)
        if cached and cached[0] == entry["version"]:
            return cached[1]
        from rosidl_runtime_py.utilities import get_message

        from fta_agent.core.subscription_manager import make_qos

        pub = self._node.create_publisher(
            get_message(entry["ros_type"]), entry["target"], make_qos(entry.get("qos"))
        )
        self._publishers[key] = (entry["version"], pub)
        return pub

    def _get_client(self, entry: dict):
        key = entry["interface_id"]
        cached = self._clients.get(key)
        if cached and cached[0] == entry["version"]:
            return cached[1]
        from rosidl_runtime_py.utilities import get_service

        client = self._node.create_client(get_service(entry["ros_type"]), entry["target"])
        self._clients[key] = (entry["version"], client)
        return client
