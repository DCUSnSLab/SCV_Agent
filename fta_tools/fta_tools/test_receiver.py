"""테스트 리시버 (FR-8) — 검증용 최소 구현. 정식 서버는 별도 프로젝트.

mosquitto 구독 → envelope(CBOR) 디코딩 → jsonl 기록 + 주기 통계 출력.
통계: 로봇별 메시지 수 / 수신 대역폭 / 종단 지연(stamp_agent 기준).

ROS 의존성 없음 — 서버 환경에서도 그대로 실행 가능.
envelope 스키마는 fta_agent와의 계약 (02 문서 §3.4)이며, 여기서는
디코딩만 하므로 cbor2로 직접 파싱한다.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import time
from collections import defaultdict

import cbor2
import paho.mqtt.client as mqtt
import zstandard


def _decode_payload(encoding: str, payload: bytes):
    """encoding 식별자(FR-3.3)에 따라 payload를 JSON 호환 값으로 디코딩."""
    if encoding == "cbor":
        return cbor2.loads(payload)
    if encoding == "cdr_zstd":
        raw = zstandard.ZstdDecompressor().decompress(payload)
        return {"_encoding": encoding, "_size": len(payload), "_cdr_size": len(raw)}
    if encoding == "voxel_zstd":
        meta = cbor2.loads(zstandard.ZstdDecompressor().decompress(payload))
        return {
            "_encoding": encoding,
            "_size": len(payload),
            "voxel_size": meta["voxel_size"],
            "count": meta["count"],
            "format": meta["format"],
        }
    if encoding == "jpeg":
        return {"_encoding": encoding, "_size": len(payload)}
    # 미지원 인코딩은 base64로 보존
    return {"_b64": base64.b64encode(payload).decode(), "_size": len(payload)}


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.per_robot = defaultdict(lambda: {"msgs": 0, "bytes": 0, "latency_sum": 0.0})
        self.window_start = time.time()

    def record(self, robot_id: str, nbytes: int, latency: float):
        with self.lock:
            s = self.per_robot[robot_id]
            s["msgs"] += 1
            s["bytes"] += nbytes
            s["latency_sum"] += latency

    def flush(self) -> str:
        with self.lock:
            elapsed = max(time.time() - self.window_start, 1e-6)
            lines = []
            for rid, s in sorted(self.per_robot.items()):
                if s["msgs"] == 0:
                    continue
                lines.append(
                    f"  {rid}: {s['msgs']} msgs, "
                    f"{s['bytes'] * 8 / elapsed / 1000:.1f} kbps, "
                    f"평균 지연 {s['latency_sum'] / s['msgs'] * 1000:.1f} ms"
                )
            self.per_robot.clear()
            self.window_start = time.time()
        return "\n".join(lines) if lines else "  (수신 없음)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FTA 테스트 리시버")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="fleet/#")
    parser.add_argument("--out", default="fta_received.jsonl", help="jsonl 기록 경로")
    parser.add_argument("--stats-interval", type=float, default=5.0)
    parser.add_argument(
        "--save-bulk", default="", metavar="DIR",
        help="bulk payload(jpeg 등)를 파일로 저장할 디렉토리 (기본: 저장 안 함)",
    )
    args = parser.parse_args(argv)

    # 로그 파일로 리다이렉트해도 통계가 실시간으로 보이도록 라인 버퍼링
    sys.stdout.reconfigure(line_buffering=True)

    stats = Stats()
    out_file = open(args.out, "a", encoding="utf-8", buffering=1)
    counters = {"received": 0, "decode_error": 0}

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"[receiver] 브로커 접속: {args.host}:{args.port}, 구독: {args.topic}")
        client.subscribe(args.topic, qos=1)

    def on_message(client, userdata, m):
        now = time.time()
        # 비-envelope 채널 (lwt 등)
        if "/sys/" in m.topic:
            print(f"[receiver] {m.topic}: {m.payload!r}")
            return
        try:
            env = cbor2.loads(m.payload)
            if args.save_bulk and env["encoding"] in ("jpeg", "voxel_zstd"):
                import pathlib

                ext = "jpg" if env["encoding"] == "jpeg" else "bin"
                p = pathlib.Path(args.save_bulk)
                p.mkdir(parents=True, exist_ok=True)
                (p / f"{env['pipeline']}_{env['seq']:06d}.{ext}").write_bytes(
                    env["payload"]
                )
            record = {
                "recv_time": now,
                "mqtt_topic": m.topic,
                "v": env["v"],
                "robot_id": env["robot_id"],
                "seq": env["seq"],
                "pipeline": env["pipeline"],
                "src_topic": env["src_topic"],
                "msg_type": env["msg_type"],
                "stamp_ros": env["stamp_ros"],
                "stamp_agent": env["stamp_agent"],
                "encoding": env["encoding"],
                "latency_ms": (now - env["stamp_agent"]) * 1000,
                "payload_size": len(env["payload"]),
                "payload": _decode_payload(env["encoding"], env["payload"]),
            }
        except Exception as e:
            counters["decode_error"] += 1
            print(f"[receiver] 디코딩 실패 ({m.topic}): {e}", file=sys.stderr)
            return
        counters["received"] += 1
        out_file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        stats.record(env["robot_id"], len(m.payload), now - env["stamp_agent"])

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="fta-test-receiver",
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    # 영속 세션: 리시버 단절 중에도 브로커가 QoS1 메시지를 보관 →
    # 에이전트 DiskBuffer drain 시점과 리시버 재접속 시점의 경합 제거
    props = mqtt.Properties(mqtt.PacketTypes.CONNECT)
    props.SessionExpiryInterval = 3600
    client.connect(args.host, args.port, clean_start=False, properties=props)
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    client.loop_start()

    print(f"[receiver] 기록: {args.out} (Ctrl+C로 종료)")
    try:
        while True:
            time.sleep(args.stats_interval)
            print(f"[receiver] --- 최근 {args.stats_interval:.0f}s 통계 "
                  f"(누적 수신 {counters['received']}, 오류 {counters['decode_error']}) ---")
            print(stats.flush())
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        out_file.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
