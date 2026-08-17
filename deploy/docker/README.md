# 가상 차량 컨테이너 — 개발용 이동체 스택

**컨테이너 1개 = 가상 모빌리티 이동체 1대.** 보유 rosbag 을 재생해 FTA 를 실제로 구동하고,
수집·중계 서버와 웹 클라이언트 개발에 쓸 업링크 트래픽을 만든다.

> ⚠️ **개발·검증 전용.** 이 이미지는 rosbag 재생기와 GPS 합성기를 품고 있어 실차에 올리면
> 안 된다. 실차 배포는 `deploy/fta_agent.service` (systemd) 를 쓴다.

---

## 1. 빠른 시작

```bash
cd SCV_Agent
docker compose -f deploy/docker/docker-compose.yml up -d --build

docker compose -f deploy/docker/docker-compose.yml ps
docker logs -f fta-r01
```

기동 후 브로커는 호스트 **1884** 포트로 열린다(1883 은 개발용 네이티브 mosquitto 가 점유).
수신 확인:

```bash
docker compose -f deploy/docker/docker-compose.yml --profile check up receiver
```

정지: `docker compose -f deploy/docker/docker-compose.yml down`

---

## 2. 구성

```
┌─ 컨테이너 (가상 차량 1대) ─────────────────────────┐
│  ros2 launch virtual_vehicle.launch.py            │
│    ├─ ros2 bag play --loop --topics ...           │
│    ├─ gps_shim   (odom → NavSatFix)               │
│    └─ fta_agent  --config /opt/fta/config/rNN.yaml│
│         DDS 는 ROS_LOCALHOST_ONLY 로 컨테이너 안에 갇힌다 │
└──────────────────────┬────────────────────────────┘
                MQTT   │
                       ▼   broker (mosquitto) 또는 콘솔 EMQX
```

| 차량 | 성격 | 파이프라인 | bag 재생 토픽 |
|---|---|---|---|
| `r01` | 풀스펙 순찰 로봇 | gps · odom · speed · **chassis** · imu · 카메라(프리뷰/스냅샷) · LiDAR(프리뷰/스냅샷) | odom_bae · hunter/velocity · hunter_status · vectornav/imu · velodyne_points · camera |
| `r02` | 경량 카메라 차량 | gps · odom · speed · 카메라 | odom_bae · hunter/velocity · camera |

`r02` 는 LiDAR·IMU·차대를 **의도적으로 빼서**, 센서 구성이 다른 차량을 서버가 어떻게
다루는지(없는 값을 지어내지 않는지) 검증하는 대조군이다.

두 차량 모두 `~/data/rosbag2_2026_01_21-18_41_02` 를 재생한다 — 위치 소스(`/odom_bae`)를
가진 bag 이 현재 이것 하나뿐이다. 재생 시작 지점(`BAG_START_OFFSET`)과 GPS 원점
오프셋을 달리해 지도상 별개 차량으로 보이게 한다.

---

## 3. 관제 콘솔 스택에 물리기

콘솔(`autodrive-ops`)을 먼저 띄운 뒤, 이 compose 의 `broker` 를 쓰지 않고 EMQX 를 가리킨다:

```yaml
# docker-compose.override.yml
services:
  broker: { profiles: ["disabled"] }        # 자체 브로커 끄기
  r01: { environment: { MQTT_HOST: emqx }, networks: [autodrive] }
  r02: { environment: { MQTT_HOST: emqx }, networks: [autodrive] }
networks:
  autodrive: { external: true, name: autodrive-ops_default }
```

---

## 4. 주요 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ROBOT_ID` | (필수) | 업링크 토픽의 `fleet/{robot_id}/...` |
| `MQTT_HOST` | `broker` | 브로커 호스트 (포트는 항상 1883) |
| `FTA_CONFIG` | `/opt/fta/config/r01.yaml` | 파이프라인 설정 |
| `BAG_PATH` | — | 비우면 bag 재생 없이 에이전트만 뜬다 |
| `BAG_TOPICS` | 전체 | 공백 구분. **storage 레벨 필터라 제외 토픽은 디스크를 안 읽는다** |
| `BAG_START_OFFSET` / `BAG_RATE` / `BAG_LOOP` | `0` / `1.0` / `1` | 재생 제어 |
| `BAG_START_DELAY` | `5.0` | 구독이 붙기 전 재생 시작 방지 |
| `GPS_ORIGIN_LAT` / `GPS_ORIGIN_LON` | `35.9` / `128.8` | ⚠️ **임시 가상 원점** |
| `GPS_OFFSET_EAST` / `GPS_OFFSET_NORTH` / `GPS_HEADING` | `0` | 차량별 지도 배치 |
| `FTA_BAG_ROOT` | `$HOME/data` | bag 루트 (읽기 전용 마운트) |

---

## 5. 설계 근거 (왜 이렇게 했는가)

**GPS shim 이 왜 필요한가.** 보유 bag 6종 506GB 전량에 `NavSatFix` 가 **0건**이다. 실차에는
GPS 가 달리지만 이 주행들은 GPS 없이 기록됐다. 지도 기반 관제 화면을 개발하려면 위치가
필요하므로 로컬 오도메트리를 원점 위경도에 투영한다.

합성을 **차량 컨테이너 안에서** 하는 것이 핵심이다. 서버가 없는 위치를 지어내면 관제 화면의
캡처가 허위 기록이 되지만, 컨테이너 경계 안이면 서버·웹은 실차와 **완전히 동일한 경로**를
탄다. GPS 포함 bag 을 확보하면 shim 을 빼기만 하면 된다.

**DDS 격리.** 컨테이너마다 네트워크 네임스페이스가 따로라 `ROS_LOCALHOST_ONLY=1` 이 곧
격리 경계가 된다. 차량마다 `ROS_DOMAIN_ID` 를 배정·관리할 필요가 없다.

**hunter_msgs 를 이미지에 넣는 이유.** 없으면 재생기가 `/hunter_status` 를
`package 'hunter_msgs' not found` 로 스킵해 **배터리 전압·조향각·차대 상태가 통째로 빠진다.**
[agilexrobotics/hunter_ros2](https://github.com/agilexrobotics/hunter_ros2) (`humble` 브랜치,
BSD, 의존은 `std_msgs` 뿐)에서 `hunter_msgs` 만 가져와 빌드한다. 호스트는 오염시키지 않는다.

**bag 토픽 필터가 곧 성능이다.** 원본은 raw Image 가 용량을 지배해(56GB 중 ~45GB) 실시간
재생 시 초당 100~440MB 를 읽는다. `--topics` 는 storage 레벨 필터라 제외한 토픽은 디스크를
아예 읽지 않는다. 더 가볍게 하려면 `ros2 bag convert` 로 축소 bag 을 미리 만든다.

---

## 6. 검증 기록 (2026-08-17)

```
빌드: hunter_msgs · fta_agent · fta_tools 3개 패키지 성공
기동: r01/r02 정상, 파이프라인 전량 error 0, publish_failed 0, 연결 connected

수신 (25초, 봉투 디코딩 + CDR 파싱 종단 확인):
  r01/chassis  48   r01/gps  37   r01/odom  47   r01/speed  48   r01/imu 108
  r01/front_cam_preview 13   r01/lidar_preview 5
  r02/gps      23   r02/odom 25   r02/speed 24   r02/front_cam_preview 24

해석:
  r01  GPS status=0 lat=35.8999639 lon=128.7999971
  r01  차대 배터리=28.00V 속도=-0.52m/s 조향=0.442rad state=0 err=0
  r02  GPS status=0 lat=35.8992514 lon=128.8015726   ← r01 대비 동 142m · 남 79m

리소스: r01 17.3% CPU / 468MB (상한 2코어·2GB), r02 14.3% / 501MB (1코어·1GB)
```

`HunterStatus.msg` 실제 정의가 서버측 CDR 파서가 가정한 레이아웃
(`f64 linear_velocity · f64 steering_angle · u8 vehicle_state · u8 control_mode ·
u16 error_code · f64 battery_voltage`)과 **정확히 일치**함을 함께 확인했다.
