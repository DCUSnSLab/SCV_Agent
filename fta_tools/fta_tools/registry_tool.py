"""테스트 레지스트리 도구 (FR-9.9c) — 파일 정의를 MQTT retained로 발행하는 CLI.

정식 레지스트리 DB·웹 UI(서버 프로젝트)가 나오기 전까지의 개발·검증 수단.
여기서 발행하는 JSON 포맷이 곧 두 프로젝트 간 계약이다:

  topic:   fleet/registry            (fleet 공통)
           fleet/{robot_id}/registry (로봇별 override, --robot-id 지정 시)
  payload: {"version": <int>, "interfaces": [<entry>...]}  (retained, QoS 1)

사용:
  ros2 run fta_tools registry_tool --file registry.yaml
  ros2 run fta_tools registry_tool --file registry.yaml --robot-id r01
  ros2 run fta_tools registry_tool --clear            # retained 제거
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import paho.mqtt.client as mqtt
import yaml

REQUIRED_FIELDS = (
    "interface_id", "name", "kind", "ros_type", "target",
    "schema", "permission_level", "default_ttl_sec", "version",
)


def validate(doc: dict) -> list:
    """발행 전 로컬 검증 — 에이전트측 검증(RegistrySyncManager)과 동일 기준."""
    errors = []
    if not isinstance(doc.get("interfaces"), list):
        return ["최상위에 interfaces 리스트가 필요합니다"]
    seen = set()
    for i, entry in enumerate(doc["interfaces"]):
        prefix = f"interfaces[{i}]"
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            errors.append(f"{prefix}: 필수 필드 누락 {missing}")
            continue
        iid = entry["interface_id"]
        if iid in seen:
            errors.append(f"{prefix}: interface_id 중복 '{iid}'")
        seen.add(iid)
        if entry["kind"] not in ("topic", "service"):
            errors.append(f"{prefix}({iid}): kind는 topic|service (action은 v2)")
        if entry["permission_level"] not in ("L0", "L1", "L2"):
            errors.append(f"{prefix}({iid}): permission_level은 L0|L1|L2 (NFR-7.4)")
        if not isinstance(entry["default_ttl_sec"], (int, float)) or entry["default_ttl_sec"] <= 0:
            errors.append(f"{prefix}({iid}): default_ttl_sec은 양수 (NFR-7.1)")
        if not isinstance(entry["schema"], dict):
            errors.append(f"{prefix}({iid}): schema는 JSON Schema 객체")
        if entry["permission_level"] == "L2":
            print(f"⚠ {iid}: L2(주행 유발) — 서버측 권한 검증 완성 전까지 "
                  f"운영 환경 사용 금지 (NFR-7.4)", file=sys.stderr)
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FTA 테스트 레지스트리 발행 도구")
    parser.add_argument("--file", help="레지스트리 정의 YAML/JSON 경로")
    parser.add_argument("--robot-id", default="", help="로봇별 override 발행 대상")
    parser.add_argument("--clear", action="store_true", help="retained 레지스트리 제거")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args(argv)

    topic = (
        f"fleet/{args.robot_id}/registry" if args.robot_id else "fleet/registry"
    )

    if args.clear:
        payload = b""  # 빈 retained 발행 = 제거
    else:
        if not args.file:
            parser.error("--file 또는 --clear 필요")
        with open(args.file, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        errors = validate(doc)
        if errors:
            print("레지스트리 검증 실패:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        payload = json.dumps(doc, ensure_ascii=False).encode("utf-8")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="fta-registry-tool",
        protocol=mqtt.MQTTv5,
    )
    client.connect(args.host, args.port)
    client.loop_start()
    info = client.publish(topic, payload, qos=1, retain=True)
    info.wait_for_publish(timeout=5)
    time.sleep(0.2)
    client.loop_stop()
    client.disconnect()

    if args.clear:
        print(f"retained 레지스트리 제거: {topic}")
    else:
        n = len(doc["interfaces"])
        print(f"레지스트리 발행 완료: {topic} (interfaces {n}개, version={doc.get('version')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
