"""DiskBuffer — store & forward (FR-5.2~5.4, 02 문서 §3.6).

- 이벤트/critical: append-only 세그먼트 파일에 전량 기록 (오래된 것부터 재전송)
- 상태 데이터: 파이프라인별 최신 1건만 유지 (고주기 백로그 재전송으로 대역폭
  낭비 금지 — FR-5.4)
- 디스크 상한 초과 시 오래된 세그먼트부터 삭제 (드롭 집계)
- 에이전트 재시작 후에도 파일 스캔으로 복구 (NFR-3.3)

레코드 포맷: [4바이트 길이(BE)] + CBOR({p, c, r, t, d})
세그먼트 단위 재전송: 세그먼트 전체 발행 성공 시 파일 삭제. 중간 실패 시
세그먼트를 보존하고 중단 — 재전송 중복은 QoS1(at-least-once) 의미론상 허용.
"""
from __future__ import annotations

import logging
import struct
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cbor2

logger = logging.getLogger(__name__)

_LEN = struct.Struct(">I")


class DiskBuffer:
    def __init__(
        self,
        dir: str,
        max_disk_mb: int = 2048,
        segment_max_bytes: int = 4 * 1024 * 1024,
    ):
        self._dir = Path(dir)
        self._events_dir = self._dir / "events"
        self._latest_dir = self._dir / "latest"
        self._events_dir.mkdir(parents=True, exist_ok=True)
        self._latest_dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_disk_mb * 1024 * 1024
        self._segment_max = segment_max_bytes
        self._lock = threading.Lock()
        self._current: Optional[object] = None  # 열려 있는 세그먼트 파일 핸들
        self._current_path: Optional[Path] = None
        self.stats = {"events_buffered": 0, "states_buffered": 0,
                      "segments_dropped": 0, "drained": 0}
        # 재시작 복구: 기존 세그먼트에 이어서 새 번호 부여
        existing = self._segments()
        self._seq = int(existing[-1].stem.split("_")[1]) + 1 if existing else 0

    # ---- 기록 ----

    def append_event(self, pipeline: str, msg_class: str, priority: str, data: bytes) -> None:
        record = self._pack(pipeline, msg_class, priority, data)
        with self._lock:
            self._ensure_capacity(len(record))
            f = self._open_segment(len(record))
            f.write(record)
            f.flush()
            self.stats["events_buffered"] += 1

    def put_latest_state(self, pipeline: str, msg_class: str, priority: str, data: bytes) -> None:
        record = self._pack(pipeline, msg_class, priority, data)
        with self._lock:
            (self._latest_dir / f"{pipeline}.rec").write_bytes(record)
            self.stats["states_buffered"] += 1

    # ---- 재전송 ----

    def drain(self, publish_fn: Callable[[dict], bool]) -> Tuple[int, bool]:
        """publish_fn(record)->bool 로 재전송. (전송 건수, 완료 여부) 반환.

        순서(02 §3.6): critical/이벤트 백로그(오래된 것부터) → 최신 상태 스냅샷.
        중간 실패 시 즉시 중단 — 남은 데이터는 다음 재연결 때 이어서 처리.
        """
        sent = 0
        with self._lock:
            self._close_segment()
            segments = self._segments()
            latest = sorted(self._latest_dir.glob("*.rec"))
        for seg in segments:
            records = self._read_records(seg)
            for rec in records:
                if not publish_fn(rec):
                    logger.warning("DiskBuffer drain 중단 (세그먼트 %s 보존)", seg.name)
                    return sent, False
                sent += 1
            seg.unlink(missing_ok=True)
        for path in latest:
            records = self._read_records(path)
            if records and not publish_fn(records[-1]):
                return sent, False
            sent += len(records[-1:])
            path.unlink(missing_ok=True)
        with self._lock:
            self.stats["drained"] += sent
        return sent, True

    # ---- 조회 ----

    def pending(self) -> Dict[str, int]:
        with self._lock:
            return {
                "event_segments": len(self._segments()),
                "latest_states": len(list(self._latest_dir.glob("*.rec"))),
                "bytes": self._total_bytes(),
            }

    def close(self) -> None:
        with self._lock:
            self._close_segment()

    # ---- 내부 ----

    @staticmethod
    def _pack(pipeline: str, msg_class: str, priority: str, data: bytes) -> bytes:
        body = cbor2.dumps(
            {"p": pipeline, "c": msg_class, "r": priority, "t": time.time(), "d": data}
        )
        return _LEN.pack(len(body)) + body

    @staticmethod
    def _read_records(path: Path) -> List[dict]:
        records = []
        raw = path.read_bytes()
        offset = 0
        while offset + 4 <= len(raw):
            (length,) = _LEN.unpack_from(raw, offset)
            offset += 4
            if offset + length > len(raw):  # 잘린 마지막 레코드 (기록 중 크래시)
                logger.warning("%s: 잘린 레코드 무시 (offset=%d)", path.name, offset)
                break
            records.append(cbor2.loads(raw[offset:offset + length]))
            offset += length
        return records

    def _segments(self) -> List[Path]:
        return sorted(self._events_dir.glob("seg_*.log"))

    def _open_segment(self, incoming: int):
        if self._current is not None:
            if self._current.tell() + incoming <= self._segment_max:
                return self._current
            self._close_segment()
        self._current_path = self._events_dir / f"seg_{self._seq:08d}.log"
        self._seq += 1
        self._current = open(self._current_path, "ab")
        return self._current

    def _close_segment(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
            self._current_path = None

    def _total_bytes(self) -> int:
        return sum(
            f.stat().st_size
            for d in (self._events_dir, self._latest_dir)
            for f in d.iterdir()
        )

    def _ensure_capacity(self, incoming: int) -> None:
        while self._total_bytes() + incoming > self._max_bytes:
            segments = self._segments()
            victim = None
            for s in segments:
                if s != self._current_path:
                    victim = s
                    break
            if victim is None:
                logger.error("DiskBuffer 상한 초과인데 삭제할 세그먼트 없음 — 기록 계속")
                return
            victim.unlink()
            self.stats["segments_dropped"] += 1
            logger.warning("디스크 상한 초과 — 오래된 세그먼트 삭제: %s", victim.name)
