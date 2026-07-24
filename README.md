# SCV_Agent — FTA (Fleet Telemetry Agent)

ROS2 기반 실외 자율주행 로봇(캠퍼스 순찰·물류, 최종 50대 규모)의 텔레메트리를 중앙 서버로 전송하고, 서버발 명령을 안전하게 실행하는 **차량측 에이전트**입니다.

> **현재 상태: v1 마일스톤 M1~M6 완료 (2026-07-24)** — 진행 상황·검증 증빙은 [docs/06_진행현황.md](docs/06_진행현황.md) 참조

## 배경

캠퍼스 내 순찰·물류용 ROS2 자율주행 로봇 다수를 운영하기 위한 웹 기반 모니터링·컨트롤 시스템이 별도로 개발 중이나, 로봇(ROS2/DDS 도메인)과 중앙 서버 사이의 데이터 전달 수단이 없는 상태입니다. FTA는 로봇 내부에서 동작하는 ROS2 노드로서 이 간극을 메웁니다:

- **업링크**: ROS2 토픽 데이터를 갈무리하여 데이터 특성에 맞는 샘플링·압축 후 MQTT로 서버 전송
- **다운링크**: 레지스트리에 등록된 인터페이스 정의를 동기화하여, 서버발 JSON 명령을 검증 체인 통과 후 ROS2 topic 발행/service 호출로 실행

## 아키텍처 개요

```
자율주행 스택 (Nav, Perception, Control ...)   ← 건드리지 않는 영역
     │  ROS2 topics (DDS)
     ▼
┌─────────────── FTA 에이전트 (별도 프로세스) ───────────────┐
│ SubscriptionManager ─▶ Pipeline × N ─▶ PriorityQueue ─▶ UplinkManager │
│       ▲                (Sampler→Codec)       │                │       │
│  ConfigLoader                           DiskBuffer            ▼       │
│  (YAML 검증/로드)                     (store&forward)   Transport(추상)│
│  ResourceGovernor · SelfTelemetry              └─ MqttTransport (v1)  │
└───────────────────────────────────────────────────┬──────────────────┘
                                     TLS, outbound  │  LTE/5G · WiFi
                                                    ▼
                                          MQTT Broker (서버측)
```

핵심 설계 원칙 (상세: [docs/02_아키텍처설계서.md](docs/02_아키텍처설계서.md)):

1. **선언적 구성** — 파이프라인은 코드가 아닌 YAML 설정으로만 정의
2. **전략의 플러그인화** — Sampler / Codec / Transport는 인터페이스 + 레지스트리 패턴
3. **로봇 무영향 격리** — 별도 프로세스, best-effort 구독, 리소스 상한
4. **불안정 네트워크 전제** — LTE/5G 단절·IP 변경을 정상 상황으로 취급
5. **전송 계층 중립** — v1은 MQTT지만 아키텍처는 프로토콜에 비결합

## v1 범위

| 구분 | 포함 여부 |
|---|---|
| 업링크 (로봇 → 서버) | **포함** |
| 다운링크 (서버 → 로봇) | **포함** — 동적 인터페이스 방식 (topic 발행 + service 호출) |
| 차량측 에이전트 | **포함 (핵심)** |
| 서버측 시스템 | 제외 — 검증용 테스트 리시버만 포함 |
| 웹 모니터링 UI | 제외 (별도 프로젝트) |

## 요구 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 22.04 |
| ROS2 | Humble |
| 언어 | Python 3.10 (rclpy) — 시스템 Python 사용 (`/usr/bin/python3`) |
| 전송 | MQTT v5 (Eclipse Paho) — 개발 시 로컬 mosquitto |
| 빌드 | colcon (ament_python) |

의존 패키지: `paho-mqtt`, `cbor2`, `zstandard`, `jsonschema`, `PyYAML` (테스트: `pytest`)

> ⚠️ pyenv 등 별도 Python이 기본인 환경에서는 rclpy와의 버전 불일치에 주의하세요. 반드시 시스템 Python 3.10 기준으로 빌드·실행해야 합니다.

## 빌드 및 실행 (M1 기준)

```bash
# 1. 의존성 설치
/usr/bin/python3 -m pip install --user paho-mqtt cbor2 zstandard jsonschema pytest
# 개발 브로커 (둘 중 하나)
sudo apt install mosquitto mosquitto-clients      # (a) 네이티브 설치
docker run -d --name fta-dev-broker -p 1883:1883 \
  -v $PWD/.dev/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf \
  eclipse-mosquitto:2                             # (b) docker

# 2. 빌드
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash

# 3. 실행 (터미널 3개)
# 터미널 A — 테스트 리시버 (수신 → jsonl 기록 + 통계)
ros2 run fta_tools test_receiver --out /tmp/fta_received.jsonl

# 터미널 B — 에이전트
export ROBOT_ID=r01
ros2 run fta_agent agent --config fta_agent/config/fta_example.yaml

# 터미널 C — 가상 데이터 발행
ros2 topic pub -r 10 /odom nav_msgs/msg/Odometry

# 4. 단위 테스트
/usr/bin/python3 -m pytest fta_agent/test/ -v
```

## 저장소 구조

```
SCV_Agent/
├── README.md
├── CLAUDE.md                  # AI 협업 개발 가이드 (아키텍처 불변 조건 포함)
├── docs/
│   ├── 01_요구사항명세서.md     # FR/NFR 전체 (안전 조항 NFR-7 포함)
│   ├── 02_아키텍처설계서.md     # 컴포넌트·시나리오·기술 스택
│   ├── 03_서버측프로젝트개요.md  # 서버 프로젝트와의 인터페이스 계약
│   ├── 04_ClaudeCode_킥오프프롬프트.md
│   ├── 05_프로젝트계획서.md     # 마일스톤 WBS·테스트 전략·리스크
│   ├── 06_진행현황.md          # 진행 트래킹 (상시 갱신)
│   ├── config_reference.md    # 설정 레퍼런스
│   ├── extending.md           # Sampler/Codec/Transport 확장 가이드
│   ├── reports/               # 대역폭·성능 측정 리포트
│   └── data_location.md       # 테스트용 rosbag 데이터 위치
├── fta_agent/                 # 메인 에이전트 패키지 (ament_python)
├── fta_tools/                 # 테스트 도구 (테스트 리시버, 레지스트리 CLI)
├── tests/integration/         # 단절·다운링크·성능 자동화 테스트
├── tools/                     # soak 테스트 등 운영 스크립트
└── deploy/                    # systemd 유닛·프로비저닝 예시
```

## 다운링크 사용 (동적 인터페이스)

```bash
# 1. 인터페이스 레지스트리 발행 (retained — 전 차량 자동 동기화)
ros2 run fta_tools registry_tool --file fta_tools/config/registry_example.yaml

# 2. 명령 발행 + 결과 확인 (검증 체인: 등록 → 스키마 → TTL → 멱등성)
python3 tests/integration/send_command.py --robot-id r01 --interface set_goal \
    --payload '{"pose": {"position": {"x": 3.0, "y": 4.0}}}'
# → {"cmd_id": "...", "status": "accepted", "detail": "/goal_pose 1회 발행"}
```

⚠️ **안전 (NFR-7)**: TTL 만료 명령은 절대 실행되지 않고 `expired`로 폐기됩니다.
E-Stop 등 안전 기능은 다운링크에 의존해서는 안 되며, L2(주행 유발) 인터페이스는
서버측 권한 검증이 완성되기 전까지 테스트 환경에서만 사용합니다.

## 마일스톤 로드맵

| 마일스톤 | 내용 | 상태 |
|---|---|---|
| **M1** | 골격 + 최소 종단 연결 (`/odom` → MQTT → 리시버) | ✅ 완료 |
| M2 | 샘플러 세트 (rate/deadband/event/on_demand) + 다중 파이프라인 | ✅ 완료 |
| M3 | 코덱 (cdr_zstd/jpeg/voxel_zstd) + 온디맨드 스냅샷 | ✅ 완료 |
| M4 | 신뢰성 (DiskBuffer, 재연결 백오프, 토큰버킷) | ✅ 완료 |
| M5 | 다운링크 (동적 인터페이스, 검증 체인, 감사 로그) | ✅ 완료 |
| M6 | 관측성 + 운영 준비 (SelfTelemetry, systemd, soak 테스트) | ✅ 완료 |

측정 리포트: [M3 대역폭](docs/reports/M3_bandwidth_report.md) · [M6 성능 NFR-1/2](docs/reports/M6_performance_report.md)
문서: [설정 레퍼런스](docs/config_reference.md) · [확장 가이드](docs/extending.md)

상세 작업 분해는 [docs/05_프로젝트계획서.md](docs/05_프로젝트계획서.md) 참조.

## 라이선스

[LICENSE](LICENSE) 참조.
