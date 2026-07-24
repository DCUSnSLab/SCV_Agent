"""다운링크 감사 로그 (NFR-7.6).

모든 명령의 수신·검증 결과·실행 결과를 로컬 jsonl에 기록한다.
서버측 보고는 cmd_result/registry_status 발행이 담당한다 — 양쪽 기록으로
"언제 누가 어떤 명령을 보냈고 차량이 어떻게 처리했는지" 재구성 가능해야 한다.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, path: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = open(self._path, "a", encoding="utf-8", buffering=1)

    def record(self, *, cmd_id, interface_id, issuer, stage: str, detail: str = "") -> None:
        entry = {
            "ts": time.time(),
            "cmd_id": cmd_id,
            "interface_id": interface_id,
            "issuer": issuer,
            "stage": stage,      # received | rejected | expired | duplicate | accepted | done | failed
            "detail": detail,
        }
        with self._lock:
            self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("[audit] %s cmd_id=%s interface=%s %s", stage, cmd_id, interface_id, detail)

    def close(self) -> None:
        with self._lock:
            self._file.close()
