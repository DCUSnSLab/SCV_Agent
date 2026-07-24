#!/usr/bin/env python3
"""다운링크 명령 발행 + cmd_result 대기 헬퍼 (M5 검증용).

예:
  python3 send_command.py --robot-id r01 --interface set_goal \
      --payload '{"pose": {"position": {"x": 3.0, "y": 4.0}}}'
  python3 send_command.py ... --issued-offset -60   # TTL 만료 시나리오
"""
import argparse
import json
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--robot-id", default="r01")
    parser.add_argument("--interface", required=True)
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--ttl", type=float, default=20.0)
    parser.add_argument("--issued-offset", type=float, default=0.0,
                        help="issued_at 오프셋(초) — 음수로 과거 발행 시뮬레이션")
    parser.add_argument("--cmd-id", default="")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    cmd_id = args.cmd_id or f"cmd-{uuid.uuid4().hex[:8]}"
    envelope = {
        "cmd_id": cmd_id,
        "interface_id": args.interface,
        "issued_at": time.time() + args.issued_offset,
        "ttl": args.ttl,
        "issuer": "send_command.py",
        "payload": json.loads(args.payload),
    }

    result_holder = {}
    got = threading.Event()

    def on_message(client, userdata, m):
        r = json.loads(m.payload)
        if r.get("cmd_id") == cmd_id:
            result_holder.update(r)
            got.set()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sendcmd-{cmd_id}", protocol=mqtt.MQTTv5,
    )
    client.on_message = on_message
    client.connect(args.host, args.port)
    client.subscribe(f"fleet/{args.robot_id}/cmd_result/{args.interface}", qos=1)
    client.loop_start()
    time.sleep(0.3)
    client.publish(
        f"fleet/{args.robot_id}/cmd/{args.interface}",
        json.dumps(envelope).encode(), qos=1,
    )

    ok = got.wait(timeout=args.timeout)
    client.loop_stop()
    client.disconnect()
    if not ok:
        print(json.dumps({"cmd_id": cmd_id, "status": "NO_RESPONSE"}))
        return 2
    print(json.dumps(result_holder, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
