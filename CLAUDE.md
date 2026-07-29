# FTA (Fleet Telemetry Agent) — 개발 가이드

## 프로젝트 컨텍스트

ROS2 기반 실외 자율주행 로봇(캠퍼스 순찰·물류, 최종 50대 규모)의 텔레메트리를 중앙 서버로 전송하는 차량측 에이전트 **FTA**를 개발한다.

- 요구사항: `docs/01_요구사항명세서.md` / 아키텍처: `docs/02_아키텍처설계서.md`
- 계획(WBS): `docs/05_프로젝트계획서.md` / 진행현황: `docs/06_진행현황.md` (세션 종료 시 갱신)
- 문서와 코드/판단이 충돌하면 **문서가 우선**한다. 문서에 없는 결정이 필요하면 임의로 정하지 말고 질문할 것.

## 확정된 기술 결정

- 언어: **Python 3.10 / rclpy** (D1 확정 2026-07-24), ROS2 **Humble**, Ubuntu **22.04**
- v1 전송: MQTT v5 (paho-mqtt), 운영은 TLS — 단 `ITransport` 인터페이스 뒤로 격리. 개발은 로컬 mosquitto 평문(1883)
- envelope: CBOR / payload 기본: CDR 원본 + zstd (M1은 cbor 코덱부터)
- 빌드: colcon 패키지(ament_python), 배포: systemd 서비스
- v1 스코프: 업링크 + 다운링크(topic 발행/service 호출, 동적 인터페이스). action·영상 스트리밍·정식 서버는 제외 (테스트 리시버·테스트 레지스트리 도구는 포함)

## 개발 환경 주의사항

- **Python**: pyenv 3.13이 기본 shim이지만 **rclpy는 시스템 Python 3.10 (`/usr/bin/python3`) 필수**. pip 설치도 `/usr/bin/python3 -m pip`로.
- 매 셸에서 `source /opt/ros/humble/setup.bash` (빌드 후엔 `source install/setup.bash`)
- 테스트 데이터: `~/data/` (rosbag). 주 데이터: `~/data/rosbag2_2026_01_21-18_41_02` (55GB, 실측 인벤토리는 05 문서 §2)
- `hunter_msgs` 커스텀 타입은 개발 머신에 typesupport 없음 — raw CDR 처리는 가능, 역직렬화 불가

## 아키텍처 불변 조건 (위반 금지)

1. Sampler / Codec / Transport는 반드시 인터페이스(ABC) + 레지스트리 패턴. 구체 클래스를 직접 참조하는 코드 금지.
2. 파이프라인 구성은 YAML로만 정의. 토픽명·전략이 소스코드에 하드코딩되면 안 된다.
3. ROS2 구독 콜백에서 인코딩·압축·I/O 금지 — 큐에 넘기고 즉시 반환.
4. 모든 구독 기본 QoS는 best-effort / 얕은 depth (파이프라인별 override 허용).
5. 네트워크 단절은 정상 상황으로 처리한다 — 어떤 단절 시나리오에서도 크래시·무한 블로킹 금지.
6. 인증 정보 하드코딩 금지 (환경변수/설정 주입).
7. **[안전 — NFR-7]** 다운링크 명령은 검증 체인(레지스트리 등록 → 스키마 → TTL → cmd_id 멱등성)을 전부 통과하지 않으면 절대 실행 금지. 검증을 우회하는 코드 경로를 만들지 말 것. TTL 만료 명령은 폐기 후 expired 응답. 이 조항은 어떤 리팩토링에서도 완화 불가.
8. **[안전 — NFR-7.3]** E-Stop 등 안전 기능이 다운링크에 의존하는 설계 금지. 다운링크 전면 장애를 정상 시나리오로 취급할 것.
9. 다운링크로 전송 가능한 대상을 소스코드에 하드코딩 금지 — 오직 레지스트리 정의로만 활성화.

## 마일스톤

M1 골격+종단 연결 → M2 샘플러 세트 → M3 코덱+Bulk → M4 신뢰성 → M5 다운링크 → M6 관측성·운영. 세부 WBS와 완료 기준은 `docs/05_프로젝트계획서.md`. 업링크(M1~M4) 완성·검증 후 다운링크(M5) 진입하며, M5 시작 전 NFR-7 절을 반드시 다시 읽을 것.

## 코드 품질 기준

- 각 마일스톤에 단위 테스트(pytest) 포함, M1부터 CI 가능한 형태 유지
- 새 Sampler/Codec 추가 방법을 `docs/extending.md`에 예제와 함께 기록 (M6)
- 커밋은 마일스톤 내 기능 단위로 분리

## 진행 방식

- 각 마일스톤 시작 전: 구현 계획을 요약해 보여주고 승인받은 뒤 진행
- 문서와 다른 판단이 필요해지면: 코드를 바꾸기 전에 근거와 함께 제안할 것
- 테스트 없이 "동작할 것"이라고 보고하지 말 것 — 실행 로그로 증명
- 세션 종료 시 `docs/06_진행현황.md` 갱신 (체크리스트, 세션 로그, 결정 로그)

## 빌드·테스트 명령

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install && source install/setup.bash
colcon test --packages-select fta_agent && colcon test-result --verbose
# 또는 단위 테스트만: /usr/bin/python3 -m pytest fta_agent/test/ -v
```
