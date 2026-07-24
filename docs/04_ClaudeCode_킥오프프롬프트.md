# Claude Code 킥오프 프롬프트 (초안)

> 사용법: 프로젝트 루트에 01·02 문서를 `docs/`로 넣은 뒤, 아래 내용을 CLAUDE.md로 저장하거나 첫 프롬프트로 사용한다. `{{ }}` 부분은 확정 후 치환.

---

## 프로젝트 컨텍스트

ROS2 기반 실외 자율주행 로봇(캠퍼스 순찰·물류, 최종 50대 규모)의 텔레메트리를 중앙 서버로 전송하는 차량측 에이전트 **FTA (Fleet Telemetry Agent)** 를 개발한다.

- 요구사항: `docs/01_요구사항명세서.md`
- 아키텍처: `docs/02_아키텍처설계서.md`
- 두 문서가 본 프롬프트와 충돌하면 **문서가 우선**한다. 문서에 없는 결정이 필요하면 임의로 정하지 말고 질문할 것.

## 확정된 기술 결정
- 언어: {{C++20 / rclcpp}} , ROS2 {{Humble}}, Ubuntu {{22.04}}
- v1 전송: MQTT v5 + TLS (Paho), 단 `ITransport` 인터페이스 뒤로 격리
- envelope: CBOR / payload 기본: CDR 원본 + zstd
- 빌드: colcon 패키지, 배포: systemd 서비스
- v1 스코프: 업링크 + 다운링크(topic 발행/service 호출, 동적 인터페이스 방식). action·영상 스트리밍·정식 서버는 제외 (테스트 리시버·테스트 레지스트리 도구는 포함)

## 아키텍처 불변 조건 (위반 금지)
1. Sampler / Codec / Transport는 반드시 인터페이스 + 레지스트리 패턴. 구체 클래스를 직접 참조하는 코드 금지.
2. 파이프라인 구성은 YAML로만 정의. 토픽명·전략이 소스코드에 하드코딩되면 안 된다.
3. ROS2 구독 콜백에서 인코딩·압축·I/O 금지 — 큐에 넘기고 즉시 반환.
4. 모든 구독 기본 QoS는 best-effort / 얕은 depth.
5. 네트워크 단절은 정상 상황으로 처리한다 — 어떤 단절 시나리오에서도 크래시·무한 블로킹 금지.
6. 인증 정보 하드코딩 금지 (환경변수/설정 주입).
7. **[안전 — NFR-7]** 다운링크 명령은 검증 체인(레지스트리 등록 → 스키마 → TTL → cmd_id 멱등성)을 전부 통과하지 않으면 절대 실행 금지. 검증을 우회하는 코드 경로를 만들지 말 것. TTL 만료 명령은 폐기 후 expired 응답. 이 조항은 어떤 리팩토링에서도 완화 불가.
8. **[안전 — NFR-7.3]** E-Stop 등 안전 기능이 다운링크에 의존하는 설계 금지. 다운링크 전면 장애를 정상 시나리오로 취급할 것.
9. 다운링크로 전송 가능한 대상을 소스코드에 하드코딩 금지 — 오직 레지스트리 정의로만 활성화.

## 마일스톤 (순서대로, 각 단계마다 동작 검증 후 진행)

> 업링크(M1~M4)를 먼저 완성·검증한 뒤 다운링크(M5)로 진입한다. 다운링크는 안전 관련 조항(NFR-7)이 있으므로 M5 시작 전 해당 절을 반드시 다시 읽을 것.

**M1 — 골격 + 최소 종단 연결**
- colcon 패키지 구조, ConfigLoader(스키마 검증 포함), ITransport/ISampler/ICodec 인터페이스와 레지스트리
- `passthrough` 샘플러 + `cbor` 코덱 + MqttTransport로 단일 토픽(`/odom`) 종단 전송
- 테스트 리시버(Python 가능): mosquitto 구독 → 디코딩 → jsonl 기록 + 통계 출력
- 완료 기준: 가상 발행 토픽이 리시버 jsonl에 기록됨

**M2 — 샘플러 세트 + 다중 파이프라인**
- rate / deadband / event / on_demand 샘플러, 우선순위 큐, 파이프라인 N개 동시 동작
- 완료 기준: 문서 §3의 데이터 인벤토리 유형별 파이프라인이 설정만으로 구성됨, 단위 테스트 통과

**M3 — 코덱 + Bulk 처리**
- cdr_zstd / jpeg(품질·리사이즈) / voxel_zstd 코덱, 로컬 스냅샷 서비스(`/fta/request_snapshot`)
- 완료 기준: 카메라·LiDAR 온디맨드 스냅샷 종단 동작, 대역폭 측정 리포트

**M4 — 신뢰성**
- DiskBuffer(store & forward, 재시작 복구), 재연결 백오프, 우선순위별 드롭/conflation 정책, 토큰버킷 대역폭 상한
- 완료 기준: 네트워크 강제 차단 5분 → 복구 시 이벤트 데이터 손실 0건 (자동화 테스트로 증명)

**M5 — 다운링크 (동적 인터페이스)**
- RegistrySyncManager(MQTT retained 기반 동기화 + 로컬 typesupport 검증 + registry_status 보고)
- JsonMessageConverter(rosidl introspection 기반 JSON→msg, 커스텀 타입 포함)
- CommandExecutor(검증 체인 → topic 발행 / service 호출 → cmd_result 응답), 감사 로그
- 테스트 레지스트리 도구(파일/SQLite → retained 발행 CLI)
- 완료 기준: (a) 커스텀 타입 인터페이스를 레지스트리 등록만으로 활성화하여 목적지 명령(set_goal) 종단 동작, (b) TTL 만료·중복 cmd_id·미등록 인터페이스·스키마 위반 4종 거부 시나리오 자동화 테스트 통과

**M6 — 관측성 + 운영 준비**
- SelfTelemetry(health 발행), ResourceGovernor, systemd 유닛(CPUQuota/MemoryMax), 구조화 로깅
- rosbag 재생 기반 성능 테스트: NFR-2 수치 측정 리포트 생성
- 완료 기준: 72시간 soak 테스트 스크립트 준비, 설정 레퍼런스·확장 가이드 문서

## 코드 품질 기준
- 각 마일스톤에 단위 테스트 포함, M1부터 CI 가능한 형태 유지
- 새 Sampler/Codec 추가 방법을 docs/extending.md에 예제와 함께 기록
- 커밋은 마일스톤 내 기능 단위로 분리

## 진행 방식
- 각 마일스톤 시작 전: 구현 계획을 요약해 보여주고 승인받은 뒤 진행
- 문서와 다른 판단이 필요해지면: 코드를 바꾸기 전에 근거와 함께 제안할 것
- 테스트 없이 "동작할 것"이라고 보고하지 말 것 — 실행 로그로 증명

---

### 치환 필요 항목 체크리스트
- [ ] 언어 확정 (D1): C++ / Python
- [ ] ROS2 배포판 (D5)
- [ ] 실 로봇 토픽명·타입으로 데이터 인벤토리 갱신 (`ros2 topic list/hz/bw` 실측)
- [ ] MQTT 브로커 접속 정보 (개발용은 로컬 mosquitto로 시작 가능)
