"""RegistrySyncManager — 동적 인터페이스 레지스트리 동기화 (FR-9.1~9.3, 02 §3.11).

- `fleet/registry` (+ 로봇별 override `fleet/{id}/registry`) retained 구독:
  구독 즉시 최신본 수신, 갱신 시 자동 재수신 — 폴링 불필요
- 각 항목의 ros_type이 로컬 typesupport에 존재하는지 검증 →
  지원/미지원 목록을 `agent/registry_status`로 보고
- 다운링크 실행 가능 대상은 여기 동기화된 정의가 유일하다 (하드코딩 금지)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Dict, Optional

from rosidl_runtime_py.utilities import get_message, get_service

from fta_agent.transports.base import ITransport, Reliability

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = (
    "interface_id", "name", "kind", "ros_type", "target",
    "schema", "permission_level", "default_ttl_sec", "version",
)
PERMISSION_LEVELS = ("L0", "L1", "L2")
KINDS = ("topic", "service")


class RegistrySyncManager:
    def __init__(self, transport: ITransport, robot_id: str, on_update=None):
        self._transport = transport
        self._robot_id = robot_id
        self._on_update = on_update  # 활성 인터페이스 변경 통지 콜백
        self._lock = threading.Lock()
        self._active: Dict[str, dict] = {}       # 검증 통과 + typesupport 지원
        self._unsupported: Dict[str, str] = {}   # interface_id → 사유
        self._registry_version: Optional[int] = None

    def start(self) -> None:
        self._transport.subscribe("fleet/registry", self._on_registry)
        self._transport.subscribe(f"fleet/{self._robot_id}/registry", self._on_registry)

    def get_interface(self, interface_id: str) -> Optional[dict]:
        """검증 체인 1단계가 사용하는 유일한 조회 경로 (FR-9.1)."""
        with self._lock:
            return self._active.get(interface_id)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "version": self._registry_version,
                "supported": sorted(self._active),
                "unsupported": dict(self._unsupported),
            }

    # ---- 내부 ----

    def _on_registry(self, topic: str, payload: bytes) -> None:
        try:
            doc = json.loads(payload.decode("utf-8"))
            interfaces = doc["interfaces"]
            assert isinstance(interfaces, list)
        except Exception as e:
            logger.error("레지스트리 파싱 실패 (%s): %s — 기존 상태 유지", topic, e)
            return

        active: Dict[str, dict] = {}
        unsupported: Dict[str, str] = {}
        for entry in interfaces:
            iid = entry.get("interface_id", "?")
            reason = self._validate_entry(entry)
            if reason:
                unsupported[iid] = reason
                continue
            reason = self._check_typesupport(entry)
            if reason:
                unsupported[iid] = reason
                continue
            active[entry["interface_id"]] = entry

        with self._lock:
            self._active = active
            self._unsupported = unsupported
            self._registry_version = doc.get("version")
        logger.info(
            "레지스트리 동기화 (v=%s): 지원 %d개 %s, 미지원 %d개 %s",
            doc.get("version"), len(active), sorted(active),
            len(unsupported), unsupported,
        )
        self.report_status()
        if self._on_update:
            self._on_update()

    @staticmethod
    def _validate_entry(entry: dict) -> Optional[str]:
        if not isinstance(entry, dict):
            return "항목이 객체가 아님"
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            return f"필수 필드 누락: {missing}"
        if entry["kind"] not in KINDS:
            return f"알 수 없는 kind '{entry['kind']}' (action은 v2)"
        if entry["permission_level"] not in PERMISSION_LEVELS:
            return f"알 수 없는 permission_level '{entry['permission_level']}' (NFR-7.4)"
        if not isinstance(entry["default_ttl_sec"], (int, float)) or entry["default_ttl_sec"] <= 0:
            return "default_ttl_sec은 양수여야 함 (NFR-7.1)"
        if not isinstance(entry["schema"], dict):
            return "schema는 JSON Schema 객체여야 함"
        return None

    @staticmethod
    def _check_typesupport(entry: dict) -> Optional[str]:
        try:
            if entry["kind"] == "topic":
                get_message(entry["ros_type"])
            else:
                get_service(entry["ros_type"])
            return None
        except (AttributeError, ModuleNotFoundError, ValueError) as e:
            return f"로컬 typesupport 없음: {entry['ros_type']} ({e})"

    def report_status(self) -> None:
        """지원/미지원 목록 서버 보고 (FR-9.3) — 서버/웹 UI의 명령 가능 여부 근거."""
        status = {
            "robot_id": self._robot_id,
            "ts": time.time(),
            **self.snapshot(),
        }
        self._transport.publish(
            "agent", "registry_status",
            json.dumps(status, ensure_ascii=False).encode("utf-8"),
            Reliability.AT_LEAST_ONCE,
        )
