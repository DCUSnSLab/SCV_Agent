# SCV_Agent — FTA (Fleet Telemetry Agent)

ROS2 기반 실외 자율주행 로봇(캠퍼스 순찰·물류, 최종 50대 규모)의 텔레메트리를 중앙 서버로 전송하고, 서버발 명령을 안전하게 실행하는 **차량측 에이전트**입니다.

> **현재 상태: v1 마일스톤 M1~M6 완료 (2026-07-24)** — 진행 상황·검증 증빙은 [docs/06_진행현황.md](docs/06_진행현황.md) 참조

| 목적 | 바로가기 |
|---|---|
| 서버도 로봇도 없이 일단 돌려보고 싶다 | [2. 빠른 시작 — 서버 없이 5분](#2-빠른-시작--서버-없이-5분) |
| 서버발 명령(다운링크)을 시험하고 싶다 | [3. 다운링크 시험 (서버 없이)](#3-다운링크-시험-서버-없이) |
| 실제 로봇에 설치해서 상시 운영하고 싶다 | [5. 실제 로봇에 설치 (운영 배포)](#5-실제-로봇에-설치-운영-배포) |
| 설정 항목을 전부 알고 싶다 | [docs/config_reference.md](docs/config_reference.md) |
| 샘플러/코덱을 새로 만들고 싶다 | [docs/extending.md](docs/extending.md) |
| 문제가 생겼다 | [7. 트러블슈팅](#7-트러블슈팅) |

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

핵심 설계 원칙 (상세: [docs/02_아키텍처설계서.md](docs/02_아키텍처설계서.md), 데이터 흐름: [docs/07_데이터흐름.md](docs/07_데이터흐름.md)):

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

---

## 1. 요구 환경과 의존성 설치

| 항목 | 값 |
|---|---|
| OS | Ubuntu 22.04 |
| ROS2 | Humble |
| 언어 | Python 3.10 (rclpy) — **시스템 Python 사용** (`/usr/bin/python3`) |
| 전송 | MQTT v5 (Eclipse Paho) — 개발 시 로컬 mosquitto |
| 빌드 | colcon (ament_python) |

```bash
# ROS/시스템 패키지 (에이전트 실행에 필수 — jpeg/voxel 코덱과 자체 상태 감시가 사용)
sudo apt install -y python3-yaml python3-numpy python3-opencv python3-psutil \
                    python3-colcon-common-extensions

# 파이썬 패키지 — 반드시 시스템 Python으로 설치
/usr/bin/python3 -m pip install --user paho-mqtt cbor2 zstandard jsonschema pytest
```

> ⚠️ pyenv/conda 등 별도 Python이 기본 `python3`인 환경에서는 **rclpy를 import할 수 없습니다**.
> 확인: `/usr/bin/python3 -c "import rclpy; print('ok')"` 가 성공해야 합니다.
> 빌드·실행·pip 설치 모두 `/usr/bin/python3` 기준으로 하세요.

---

## 2. 빠른 시작 — 서버 없이 5분

**목표**: 중앙 서버도 실제 로봇도 없이, 로컬 PC 한 대에서 업링크 종단(ROS2 토픽 → 샘플링/인코딩 → MQTT → 수신 기록)을 눈으로 확인합니다.
서버 자리는 저장소에 포함된 **테스트 리시버**가, 로봇 자리는 **`ros2 topic pub` 가짜 발행자**가 대신합니다.

### 2.1 로컬 MQTT 브로커 띄우기

둘 중 하나만 하면 됩니다.

```bash
# (a) 네이티브 mosquitto — 설치하면 systemd 서비스가 자동 기동되고
#     기본 설정에서 localhost:1883 익명 접속이 허용되므로 추가 설정이 필요 없다
sudo apt install -y mosquitto mosquitto-clients
systemctl is-active mosquitto        # active 여야 함
#   서비스를 쓰지 않고 직접 띄우려면: mosquitto -c .dev/mosquitto/mosquitto.conf &

# (b) docker
docker run -d --name fta-dev-broker -p 1883:1883 \
  -v $PWD/.dev/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf \
  eclipse-mosquitto:2
```

확인: `mosquitto_sub -h localhost -t 'fleet/#' -v` 가 에러 없이 대기하면 정상.
(개발 브로커는 평문·익명입니다. 운영 브로커는 TLS+인증 필수 — 5.4 참조)

### 2.2 빌드

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install      # 개발용. 배포 빌드는 5.2 참조
source install/setup.bash
```

### 2.3 실행 (터미널 3개)

모든 터미널에서 먼저 `source /opt/ros/humble/setup.bash && source install/setup.bash`.

```bash
# 터미널 A — 서버 역할: 수신 → jsonl 기록 + 5초마다 통계
ros2 run fta_tools test_receiver --out /tmp/fta_received.jsonl

# 터미널 B — 에이전트
export ROBOT_ID=r01
ros2 run fta_agent agent --config fta_agent/config/fta_example.yaml

# 터미널 C — 로봇 역할: /odom 5Hz 가짜 발행
ros2 topic pub -r 5 /odom nav_msgs/msg/Odometry "{}"
```

### 2.4 확인 포인트

**터미널 B (에이전트)** — 구독·접속·통계가 이렇게 찍히면 정상입니다.

```
[INFO] fta_agent.core.subscription_manager: 구독: /odom (nav_msgs/msg/Odometry) → 파이프라인 'odom'
[INFO] fta_agent: FTA 기동 완료: robot_id=r01, 파이프라인 1개, transport=connecting
[INFO] fta_agent.transports.mqtt_transport: MQTT 접속됨: localhost:1883
[INFO] fta_agent: 파이프라인 'odom' 통계: {'in': 34, 'sampled_out': 0, 'encoded': 34, ... 'error': 0}
[INFO] fta_agent: 업링크 통계: {'published': 34, 'publish_failed': 0, ...}, 연결: connected
```

**터미널 A (리시버)** — 수신량·대역폭·지연이 집계됩니다.

```
[receiver] 브로커 접속: localhost:1883, 구독: fleet/#
[receiver] --- 최근 5s 통계 (누적 수신 23, 오류 0) ---
  r01: 23 msgs, 39.7 kbps, 평균 지연 0.4 ms
```

**기록 파일** — envelope가 디코딩되어 한 줄 1메시지로 쌓입니다.

```bash
wc -l /tmp/fta_received.jsonl
head -1 /tmp/fta_received.jsonl | /usr/bin/python3 -m json.tool | head -20
# {"mqtt_topic": "fleet/r01/state/odom", "robot_id": "r01", "seq": 0, "pipeline": "odom",
#  "encoding": "cbor", "latency_ms": 0.38, "payload_size": 939, "payload": { ... }}
```

판정 기준 3가지: **`error: 0`**, **`publish_failed: 0`**, **`seq`가 0부터 결손 없이 증가**.

### 2.5 종료 (중요)

`ros2 run` 을 Ctrl+C 대신 `kill` 로 끊으면 **자식 파이썬 프로세스가 살아남습니다.**
살아남은 에이전트는 같은 MQTT client_id(`fta-{robot_id}`)로 재접속하여 다음에 띄운 에이전트를 계속 끊어버립니다(브로커의 중복 client_id 킥).

```bash
# 각 터미널에서 Ctrl+C 로 종료한 뒤, 잔존 확인
ps aux | grep -E "[f]ta_agent|[t]est_receiver"     # 출력이 없어야 정상
```

### 2.6 (선택) 원시 MQTT / 에이전트 자체 상태 확인

```bash
# 브로커에 실제로 무엇이 흐르는지 (payload는 CBOR이라 사람이 읽을 수 없음 — 토픽 확인용)
mosquitto_sub -h localhost -t 'fleet/#' -v

# 에이전트 자체 상태 — 서버 없이 로봇 내부에서 바로 확인 가능
ros2 topic echo /fta/health --once
# data: '{"robot_id": "r01", "uptime_sec": 10.0, "conn_state": "connected", "pipelines": {...},
#         "uplink": {...}, "queue": {...}, "buffer": null, "resource": {"cpu_pct":.., "rss_mb":..}}'
```

---

## 3. 다운링크 시험 (서버 없이)

다운링크로 실행 가능한 대상은 **레지스트리 등록으로만** 결정됩니다 (코드/설정에 하드코딩하는 경로는 존재하지 않음, FR-9.1).
서버가 없어도 `registry_tool`이 서버 대신 레지스트리를 발행하고, `send_command.py`가 서버 대신 명령을 던집니다.

```bash
# 0) 브로커 실행 상태에서, 다운링크가 켜진 설정으로 에이전트 기동
export ROBOT_ID=r01 FTA_AUDIT_LOG=/tmp/fta_audit.jsonl
ros2 run fta_agent agent --config fta_agent/config/fta_m5_test.yaml

# 1) 인터페이스 레지스트리 발행 (retained — 접속하는 전 차량이 자동 동기화)
ros2 run fta_tools registry_tool --file fta_tools/config/registry_example.yaml
#    에이전트 로그: 레지스트리 동기화 (v=1): 지원 2개 [...], 미지원 1개 {...}

# 2) 정상 명령 — 검증 체인(등록 → 스키마 → TTL → cmd_id 멱등성) 통과 후 실행
/usr/bin/python3 tests/integration/send_command.py --robot-id r01 --interface set_goal \
    --payload '{"pose": {"position": {"x": 3.5, "y": 4.0}}}'
# → {"cmd_id": "...", "status": "accepted", "detail": "/goal_pose 1회 발행"}

# 3) 실제로 ROS2 쪽에 나갔는지 확인 (다른 터미널에서 미리 띄워둘 것)
ros2 topic echo /goal_pose geometry_msgs/msg/PoseStamped
```

거부 동작도 같은 방식으로 직접 확인할 수 있습니다 (모두 **실행되지 않고** 응답만 돌아옵니다).

| 시험 | 명령 | 기대 응답 |
|---|---|---|
| TTL 만료 | `... --interface set_goal --payload '{"pose":{"position":{"x":1,"y":1}}}' --issued-offset -60` | `"status": "expired"` |
| 중복 cmd_id | 같은 `--cmd-id` 로 두 번 전송 | 재실행 없이 `기존 결과 재응답` |
| 미등록 인터페이스 | `--interface not_registered` | `"status": "rejected"` |
| 스키마 위반 | `--payload '{"pose":{"position":{"x":1}}}'` (y 누락) | `"status": "rejected"` |
| TTL 과다 | `--ttl 999` (인터페이스 default_ttl 30초 초과) | `"status": "rejected"` |

전 과정은 감사 로그에 남습니다: `cat /tmp/fta_audit.jsonl` (NFR-7.6).

⚠️ **안전 (NFR-7)**
- TTL이 만료된 명령은 어떤 경우에도 실행되지 않고 폐기됩니다.
- **E-Stop 등 안전 기능을 다운링크에 의존시키지 마십시오** — 다운링크 전면 장애는 정상 시나리오로 취급합니다 (NFR-7.3).
- 예시 레지스트리의 `set_goal`은 주행을 유발하는 **L2** 등급입니다. 서버측 권한 검증이 완성되기 전에는 테스트 환경에서만 사용하십시오 (NFR-7.4).

---

## 4. 자동화 테스트

| 명령 | 확인 내용 | 소요 |
|---|---|---|
| `source install/setup.bash && /usr/bin/python3 -m pytest fta_agent/test/ -v` | 단위 테스트 60건 | 수 초 |
| `colcon test --packages-select fta_agent && colcon test-result --all` | 위와 동일(빌드 시스템 경유) | 수 초 |
| `bash tests/integration/m5_downlink_test.sh` | 다운링크 종단 + 거부 4종 (NFR-7) | ~1분 |
| `bash tests/integration/m4_disconnect_test.sh 60` | 브로커 차단 60초 → 복구, 이벤트 손실 0건 (전용 브로커 18883 사용) | 인자+α |
| `bash tests/integration/m6_perf_test.sh` | CPU/RSS/지연 (NFR-1/2) — **rosbag 필요** ([docs/data_location.md](docs/data_location.md)) | ~2분 |
| `bash tools/soak_test.sh 1` | 장시간 연속 운영 RSS 증가 판정 (기본 72시간, 인자로 단축) | 지정 시간 |

> 통합 테스트는 로컬 브로커와 DDS를 함께 씁니다. **2.5의 잔존 프로세스를 반드시 정리한 뒤** 실행하세요 — 살아있는 에이전트가 있으면 client_id 중복으로 대부분의 항목이 실패합니다.

---

## 5. 실제 로봇에 설치 (운영 배포)

### 5.1 배치 레이아웃

`deploy/fta_agent.service`가 전제하는 구조입니다.

```
/opt/fta/src/SCV_Agent/   저장소 (로봇에서 직접 빌드)
/opt/fta/install/         colcon 산출물 → 서비스가 source
/opt/fta/config/fta.yaml  이 로봇의 파이프라인 설정
/etc/fta/fta.env          로봇별 프로비저닝 값 (ID·브로커·인증) — 저장소에 커밋 금지
/var/lib/fta/             DiskBuffer·감사 로그 (쓰기 권한 필요)
```

### 5.2 설치

```bash
# 0) 의존성 (1장) 설치 후
sudo mkdir -p /opt/fta/src /opt/fta/config /etc/fta /var/lib/fta
sudo chown -R $USER:$USER /opt/fta

# 1) 소스 배치 + 빌드 — 로봇에서 직접 빌드한다
cd /opt/fta/src && git clone https://github.com/DCUSnSLab/SCV_Agent.git
cd /opt/fta && source /opt/ros/humble/setup.bash
colcon build            # ⚠️ 배포에는 --symlink-install 을 쓰지 말 것 (소스 트리가 런타임 의존이 됨)

# 2) 실행 계정 + 디렉토리 권한
sudo useradd -r -s /usr/sbin/nologin fta 2>/dev/null || true
sudo chown -R fta:fta /var/lib/fta /opt/fta
```

### 5.3 이 로봇에 맞는 설정 작성

`/opt/fta/config/fta.yaml`을 만듭니다. **토픽명·전송 정책은 전부 이 파일에서만 정의**합니다.

먼저 실제 로봇에서 무엇이 흐르는지 조사하십시오.

```bash
ros2 topic list                      # 대상 후보
ros2 topic info -v /odom             # 타입·QoS(신뢰성/내구성) — 설정의 msg_type/qos에 반영
ros2 topic hz /odom                  # 원래 주기 → 얼마나 줄일지 판단
ros2 topic bw /velodyne_points       # 대역폭 → bulk 여부 판단
```

데이터 유형별 권장 조합:

| 데이터 | sampler | codec | priority | msg_class |
|---|---|---|---|---|
| 위치/속도 (고주기 상태) | `rate` (1~2Hz) | `cdr_zstd` | high | state |
| IMU 등 보조 상태 | `rate` (5Hz) | `cdr_zstd` | normal | state |
| 배터리·온도 (느린 변화) | `deadband` (field·threshold) | `cbor` | normal | state |
| E-Stop·모드 전환 (사건) | `event` (`condition: changed`) | `cbor` | **critical** | **event** |
| 비주기 1회 발행 (경로 등) | `passthrough` + `qos.durability: transient_local` | `cbor` | high | state |
| 카메라 프리뷰 | `rate` (0.5Hz) | `jpeg` (quality/max_width) | low | bulk |
| LiDAR 프리뷰 | `rate` (0.2Hz) | `voxel_zstd` | low | bulk |
| 요청 시에만 필요한 고품질 | `on_demand` | `jpeg`/`voxel_zstd` | low | bulk |

`msg_class`는 **단절 시 보존 정책**을 결정합니다 — `event`는 전량 디스크 보존, `state`는 최신값만, `bulk`는 폐기.

최소 운영 템플릿 (전체 항목은 [docs/config_reference.md](docs/config_reference.md), 실전 예시는 `fta_agent/config/fta_bag_replay.yaml`):

```yaml
agent:
  robot_id: ${ROBOT_ID}              # 환경변수로만 주입 (하드코딩 금지)
  buffer:
    dir: ${FTA_BUFFER_DIR}           # 지정해야 단절 시 store & forward 동작
    max_disk_mb: 2048
  resource:
    bandwidth_limit_kbps: 1000       # LTE 요금제에 맞게
    cpu_limit_pct: 20
    mem_limit_mb: 512
  telemetry: { interval_sec: 10 }

transport:
  type: mqtt
  mqtt:
    host: mqtt.example.com           # 서버 브로커
    port: 8883
    tls: true                        # 운영 필수 (NFR-5.1)
    keepalive_sec: 30

pipelines:
  - name: odom
    topic: /odom
    msg_type: nav_msgs/msg/Odometry
    sampler: { type: rate, hz: 2 }
    codec: { type: cdr_zstd }
    priority: high
    msg_class: state

  - name: estop
    topic: /vehicle/estop
    msg_type: std_msgs/msg/Bool
    sampler: { type: event, field: data, condition: changed }
    codec: { type: cbor }
    priority: critical
    msg_class: event
```

설정은 기동 시 스키마 검증되며, 오류가 있으면 원인을 찍고 **즉시 종료**합니다 (FR-6.3). 로봇에 올리기 전 검증:

```bash
source /opt/fta/install/setup.bash
ROBOT_ID=test FTA_BUFFER_DIR=/tmp/b ros2 run fta_agent agent --config /opt/fta/config/fta.yaml
```

### 5.4 프로비저닝 (로봇별 값·인증)

```bash
sudo cp deploy/fta.env.example /etc/fta/fta.env
sudo nano /etc/fta/fta.env        # ROBOT_ID, 인증 정보를 이 로봇 값으로
sudo chown fta:fta /etc/fta/fta.env && sudo chmod 600 /etc/fta/fta.env
```

```ini
ROBOT_ID=r01                          # 차량마다 유일 (MQTT 네임스페이스·client_id의 근거)
FTA_CONFIG=/opt/fta/config/fta.yaml
ROS_DOMAIN_ID=0                       # 로봇의 DDS 도메인과 일치시킬 것
FTA_MQTT_USERNAME=robot-r01           # 로봇별 개별 크리덴셜 (유출 시 개별 폐기)
FTA_MQTT_PASSWORD=...
FTA_BUFFER_DIR=/var/lib/fta/buffer
FTA_AUDIT_LOG=/var/lib/fta/audit.jsonl
```

- 인증 정보는 **환경변수로만** 주입됩니다. 설정 파일·소스에 넣지 마십시오 (NFR-5.3).
- `mqtt.tls: true`는 **시스템 CA 신뢰 저장소**를 사용합니다. 사설 CA라면 로봇 OS의 신뢰 저장소에 CA 인증서를 등록하십시오(`/usr/local/share/ca-certificates/` + `update-ca-certificates`).
- 방화벽은 **아웃바운드만** 열면 됩니다 (에이전트는 서버에 접속하는 쪽입니다).

### 5.5 systemd 등록

```bash
sudo cp deploy/fta_agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fta_agent
systemctl status fta_agent
```

유닛이 제공하는 것: 크래시 시 자동 재시작(`Restart=always`, 5초), OS 레벨 방어선 `CPUQuota=20%` / `MemoryMax=512M`, 비특권 계정 실행, `--log-format json`.

### 5.6 설치 후 점검

```bash
# 1) 기동 로그 (JSON 한 줄 = 1 이벤트)
journalctl -u fta_agent -f

# 2) 에이전트 자체 상태 — 로봇 내부에서
source /opt/fta/install/setup.bash
ros2 topic echo /fta/health --once      # conn_state: connected, error/publish_failed 0 확인

# 3) 서버측(또는 노트북)에서 수신 확인
ros2 run fta_tools test_receiver --host mqtt.example.com --topic 'fleet/r01/#' --out /tmp/r01.jsonl

# 4) 재시작 복구 확인
sudo systemctl restart fta_agent && journalctl -u fta_agent -n 20
```

체크리스트: `conn_state=connected` / 파이프라인 `error: 0` / `publish_failed: 0` / `queue.dropped` 미증가 / RSS가 `mem_limit_mb` 이내.

### 5.7 업데이트 · 제거

```bash
# 업데이트
cd /opt/fta/src/SCV_Agent && git pull
cd /opt/fta && source /opt/ros/humble/setup.bash && colcon build
sudo systemctl restart fta_agent

# 제거
sudo systemctl disable --now fta_agent
sudo rm /etc/systemd/system/fta_agent.service && sudo systemctl daemon-reload
# 필요 시 /opt/fta /etc/fta /var/lib/fta 삭제
```

---

## 6. 운영 중 관측

| 관측 지점 | 방법 | 내용 |
|---|---|---|
| 로봇 내부 | `ros2 topic echo /fta/health` | uptime, conn_state, 파이프라인별 통계, 큐/버퍼, CPU·RSS |
| 서버 | `fleet/{robot_id}/agent/health` | 위와 동일 (heartbeat, 기본 10초) |
| 서버 | `fleet/{robot_id}/sys/lwt` | Last Will — 비정상 단절 감지 |
| 서버 | `fleet/{robot_id}/agent/registry_status` | 레지스트리 동기화 결과 (미지원 인터페이스 보고 포함) |
| 로봇 | `journalctl -u fta_agent` | 구조화(JSON) 로그 |
| 로봇 | `${FTA_AUDIT_LOG}` | 다운링크 명령 수신·검증·실행 전 과정 (NFR-7.6) |

MQTT 토픽 네임스페이스 전체(서버 계약)는 [docs/config_reference.md](docs/config_reference.md) 말미 참조.

---

## 7. 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `ModuleNotFoundError: No module named 'rclpy'` | pyenv/conda Python으로 실행 중. `/usr/bin/python3` 사용, `source /opt/ros/humble/setup.bash` 확인 |
| pytest에서 `No module named 'fta_agent.codecs'` | `source install/setup.bash` 없이 저장소 루트에서 실행함. 소스 후 재실행 |
| `설정 오류로 기동 중단: 설정에 사용된 환경변수가 정의되지 않았습니다: ['ROBOT_ID']` | `export ROBOT_ID=...` 누락 (systemd라면 `/etc/fta/fta.env`) |
| `msg_type '...'의 typesupport를 찾을 수 없습니다` | 커스텀 메시지 패키지를 source하지 않았거나 로봇에 설치되지 않음. 해당 워크스페이스를 source한 뒤 기동 |
| 로그에 `연결: connecting`만 계속 | 브로커 주소/포트/TLS/인증 확인. **크래시하지 않고 재접속을 반복하는 것이 정상 동작**입니다 (단절은 정상 상황) |
| `MQTT 단절 (정상 상황으로 처리, 자동 재접속)`이 수 초 간격 반복 | client_id 중복 — 같은 `ROBOT_ID`의 에이전트가 이미 떠 있음. 잔존 프로세스 확인(2.5) 또는 로봇별 유일 ID 부여 |
| 파이프라인 통계 `in: 0` | 토픽명 오타, DDS 도메인 불일치(`ROS_DOMAIN_ID`), 또는 발행자 미기동. `ros2 topic hz <topic>`으로 확인 |
| 비주기 latched 토픽을 못 받음 | `qos: { durability: transient_local, reliability: reliable, depth: 1 }` 지정 필요 |
| 리시버 로그에 `디코딩 실패 (fleet/registry)` | 정상입니다 — 레지스트리는 JSON, 리시버는 텔레메트리 envelope(CBOR) 디코더라서 나는 메시지 |
| 단절 후 복구했는데 이벤트가 누락 | `agent.buffer.dir` 미설정 시 디스크 버퍼가 비활성입니다. 설정 후 재기동 |
| bulk 파이프라인이 멈춤(`paused`) | ResourceGovernor가 CPU/RSS 임계 초과로 절제 중. 정상 보호 동작이며 임계 이하로 내려가면 재개 |
| `ros2 topic echo` 실행 시 ros2cli XML-RPC 트레이스백 | ROS2 데몬 이상. `ros2 daemon stop && ros2 daemon start` |

---

## 저장소 구조

```
SCV_Agent/
├── README.md
├── CLAUDE.md                  # AI 협업 개발 가이드 (아키텍처 불변 조건 포함)
├── docs/
│   ├── 01_요구사항명세서.md     # FR/NFR 전체 (안전 조항 NFR-7 포함)
│   ├── 02_아키텍처설계서.md     # 컴포넌트·시나리오·기술 스택
│   ├── 03_서버측프로젝트개요.md  # 서버 프로젝트와의 인터페이스 계약
│   ├── 05_프로젝트계획서.md     # 마일스톤 WBS·테스트 전략·리스크
│   ├── 06_진행현황.md          # 진행 트래킹 (상시 갱신)
│   ├── 07_데이터흐름.md         # 업링크/다운링크/스레드 모델 다이어그램
│   ├── config_reference.md    # 설정 레퍼런스 (전 항목)
│   ├── extending.md           # Sampler/Codec/Transport 확장 가이드
│   ├── reports/               # 대역폭·성능 측정 리포트
│   └── data_location.md       # 테스트용 rosbag 데이터 위치
├── fta_agent/                 # 메인 에이전트 패키지 (ament_python)
│   ├── config/                # 설정 예시 (example / m2 / bag_replay / m4 / m5)
│   └── test/                  # 단위 테스트 60건
├── fta_tools/                 # 테스트 리시버, 레지스트리 CLI (서버 대역용)
├── tests/integration/         # 단절·다운링크·성능 자동화 테스트
├── tools/                     # soak 테스트 등 운영 스크립트
└── deploy/                    # systemd 유닛·프로비저닝 예시
```

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
상세 작업 분해는 [docs/05_프로젝트계획서.md](docs/05_프로젝트계획서.md) 참조.

## 라이선스

[LICENSE](LICENSE) 참조.
