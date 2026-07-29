# FTA 설정 레퍼런스

단일 YAML 파일로 에이전트 전체를 선언한다 (FR-6.1). 스키마 검증은 기동 시
수행되며 오류는 원인과 함께 즉시 실패한다 (FR-6.3). `${ENV_VAR}` 문법으로
환경변수를 주입한다 — 미정의 시 기동 실패 (FR-6.2).

전체 예시: `fta_agent/config/fta_bag_replay.yaml`, `fta_m5_test.yaml`

## agent

| 키 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `robot_id` | ✅ | — | 로봇 식별자. MQTT 네임스페이스 `fleet/{robot_id}/...`에 사용 |
| `queue_maxlen_per_priority` | | 256 | 우선순위별 송신 큐 길이. 포화 시: low/normal 오래된 것 드롭, high conflation, **critical·이벤트는 DiskBuffer로 이관**(버퍼 미설정 시 드롭) |
| `buffer.dir` | | (없으면 버퍼 비활성) | DiskBuffer 디렉토리 — 단절 시 store & forward (FR-5.2) |
| `buffer.max_disk_mb` | | 2048 | 디스크 상한. 초과 시 오래된 세그먼트 삭제 (FR-5.3) |
| `resource.bandwidth_limit_kbps` | | (무제한) | 토큰버킷 업링크 상한. critical은 우회 (NFR-2.1/2.5) |
| `resource.cpu_limit_pct` | | 20 | ResourceGovernor CPU 임계 — 초과 시 bulk 일시정지 (NFR-1.3) |
| `resource.mem_limit_mb` | | 512 | ResourceGovernor RSS 임계 (NFR-1.4) |
| `telemetry.interval_sec` | | 10 | health 발행 주기 (`fleet/{id}/agent/health` + `/fta/health`) |

## transport

| 키 | 필수 | 설명 |
|---|---|---|
| `type` | ✅ | 레지스트리 키. v1: `mqtt` |
| `mqtt.host` / `mqtt.port` | ✅ / (1883) | 브로커 주소 |
| `mqtt.tls` | (false) | TLS 사용 — 운영 필수 (NFR-5.1). 인자 없이 켜면 **OS 신뢰저장소**로 서버 인증서를 검증 (공인 CA용) |
| `mqtt.ca_certs` | | 사설 CA 인증서 경로. 자체 서명 브로커 인증서를 쓸 때만 필요 (경로는 `${ENV}` 주입 권장) |
| `mqtt.certfile` / `mqtt.keyfile` | | 클라이언트 인증서·키 (mTLS). 둘 다 지정해야 하며 하나만 주면 기동 실패 |
| `mqtt.tls_insecure` | (false) | 인증서 호스트명 검증 생략 — IP 접속 테스트 한정, **운영 금지** |
| `mqtt.keepalive_sec` | (30) | 단절 감지 주기 |
| `mqtt.client_id` | (`fta-{robot_id}`) | 로봇별 유일해야 함 (중복 시 상호 세션 킥) |
| `mqtt.ack_timeout_sec` | (5) | QoS1 PUBACK 대기 시간 — 초과 시 DiskBuffer 보존 |

인증: `FTA_MQTT_USERNAME` / `FTA_MQTT_PASSWORD` 환경변수로만 주입 (NFR-5.3).

## pipelines[] (토픽당 1개)

| 키 | 필수 | 설명 |
|---|---|---|
| `name` | ✅ | 파이프라인 이름 (`[a-zA-Z0-9_]+`, 중복 불가). MQTT 토픽 마지막 segment |
| `topic` | ✅ | 구독할 ROS2 토픽 (`/`로 시작) |
| `msg_type` | ✅ | `pkg/msg/Type` 형식. 기동 시 typesupport 존재 검증 |
| `sampler` | ✅ | `{ type: <키>, ...파라미터 }` — 아래 샘플러 표 |
| `codec` | ✅ | `{ type: <키>, ...파라미터 }` — 아래 코덱 표 |
| `priority` | ✅ | `critical` \| `high` \| `normal` \| `low` — critical=QoS1+대역폭 상한 우회 |
| `msg_class` | (state) | `state` \| `event` \| `bulk` — MQTT 채널 분류 + 단절 시 보존 정책 (event=전량, state=최신값, bulk=폐기) |
| `enabled` | (true) | false면 파이프라인 생성 안 함 |
| `qos.reliability` | (best_effort) | `best_effort` \| `reliable` (FR-1.3: 기본 best_effort) |
| `qos.durability` | (volatile) | `transient_local`이면 latched 토픽 수신 (FR-1.5) |
| `qos.depth` | (5) | 구독 큐 깊이 |

### 샘플러 (FR-2)

| type | 파라미터 | 동작 |
|---|---|---|
| `passthrough` | — | 무가공 통과 (비주기 발행 토픽용) |
| `rate` | `hz` (양수) | 목표 주기로 다운샘플 |
| `deadband` | `field`, `threshold` | 필드 변화량이 임계 이상일 때만 통과. 첫 메시지는 통과 |
| `event` | `field`, `condition`(changed\|eq\|ne\|gt\|gte\|lt\|lte), `value` | 엣지 트리거 즉시 전송(PASS_AND_FLUSH). changed 외에는 `value` 필수 |
| `on_demand` | — | 요청 시 1회 통과. `/fta/request_snapshot/{name}` 서비스 및 다운링크 service 인터페이스로 트리거 |

`field`는 점 구분 경로: `pose.pose.position.x`, `status[0].level`

### 코덱 (FR-3)

| type | 파라미터 | encoding 식별자 | 용도 |
|---|---|---|---|
| `cbor` | — | `cbor` | 필드 단위 dict→CBOR. 수신측 무의존 디코딩. typesupport 필요 |
| `cdr_zstd` | `level` (1~22, 기본 3) | `cdr_zstd` | CDR 원본+zstd. typesupport 불필요, 서버 rosbag 재기록에 유리 (기본 권장) |
| `jpeg` | `quality` (1~100, 기본 60), `max_width` (0=제한 없음) | `jpeg` | Image/CompressedImage → JPEG |
| `voxel_zstd` | `voxel_size` (m, 기본 0.2), `level` | `voxel_zstd` | PointCloud2 복셀 다운샘플. 디코딩: zstd 해제→CBOR {voxel_size, count, format, data} |

## downlink (FR-9, NFR-7)

| 키 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `enabled` | | false | 다운링크 활성화 (opt-in) |
| `command_timeout_sec` | | 10 | service kind 호출 타임아웃 (FR-9.6) |
| `audit_log` | | `fta_audit.jsonl` | 감사 로그 경로 (NFR-7.6) |

실행 가능 대상은 **레지스트리 동기화로만** 결정된다 — 설정/코드에 다운링크
대상을 정의하는 방법은 존재하지 않는다 (FR-9.1). 레지스트리 항목 스키마와
발행 방법은 `fta_tools/config/registry_example.yaml` 및
`ros2 run fta_tools registry_tool --help` 참조.

## MQTT 토픽 네임스페이스 (02 문서 §3.7 — 서버 계약)

```
fleet/{robot_id}/state/{pipeline}        QoS0  상태
fleet/{robot_id}/event/{pipeline}        QoS1  이벤트
fleet/{robot_id}/bulk/{pipeline}         QoS0  대용량
fleet/{robot_id}/agent/health            QoS0  자체 상태 (heartbeat)
fleet/{robot_id}/agent/registry_status   QoS1  레지스트리 동기화 보고
fleet/{robot_id}/sys/lwt                 QoS1  Last Will
fleet/{robot_id}/cmd/{interface}         QoS1  다운링크 명령 (JSON)
fleet/{robot_id}/cmd_result/{interface}  QoS1  명령 결과 (JSON)
fleet/registry                           retained  레지스트리 배포 (JSON)
fleet/{robot_id}/registry                retained  로봇별 override
```

서버측 브로커 요구사항: persistence 활성 + 인제스천 서비스는 내구 세션
(clean_start=false) 사용 — 에이전트 재전송(drain)과 서버 재접속의 경합 방지.
