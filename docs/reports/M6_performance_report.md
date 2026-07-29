# M6 성능 테스트 리포트 (NFR-1 / NFR-2)

- 측정일: 2026-07-24
- 방법: `tests/integration/m6_perf_test.sh` — 실측 rosbag 60초 재생(4개 토픽:
  odom 50Hz, IMU 20Hz, 카메라 30Hz, Velodyne 10Hz) + 파이프라인 7개
  (`fta_bag_replay.yaml`) + 1초 간격 프로세스 리소스 샘플링
- 환경: 개발 머신 로컬 브로커 (실망 지연 미포함 — 종단 지연 실측은 LTE 파일럿에서)

## NFR-1 로봇 무영향 (리소스 상한)

| 항목 | 측정값 | 요구사항 | 판정 |
|---|---|---|---|
| CPU (Bulk 인코딩 포함) | 평균 8.0% / p95 10.0% / 최대 12.0% | ≤ 1코어의 20% (NFR-1.3) | **PASS** |
| 메모리 RSS | 평균 130 MB / 최대 136 MB | ≤ 512 MB (NFR-1.4) | **PASS** |

- 측정 부하: 카메라 30Hz rgb8(1.35MB/프레임) 상시 수신·역직렬화 + JPEG 0.5fps
  인코딩 + LiDAR 복셀 0.2Hz — v1 최대 부하 구성에 해당
- systemd `CPUQuota=20%`/`MemoryMax=512M`이 OS 레벨 백스톱 (deploy/fta_agent.service)

## NFR-2 네트워크·성능

| 항목 | 측정값 | 요구사항 | 판정 |
|---|---|---|---|
| 평시 업링크 대역폭 | 175 kbps (프리뷰 포함) | 상한 1 Mbps, 목표 100~300 kbps | **PASS** |
| 상태 데이터 지연(에이전트 처리→수신) | p50 0.33 ms / p95 0.51 ms | 평시 ≤ 1 s (NFR-2.2) | **PASS**¹ |
| 이벤트 지연 | p50 0.33 ms (M2 측정) | 평시 ≤ 500 ms (NFR-2.3) | **PASS**¹ |
| 온디맨드 스냅샷 요청→수신 | 0.74 s | ≤ 3 s (NFR-2.4) | **PASS**¹ |
| 대역폭 상한 절제 | 토큰버킷 (critical 우회) — M4 테스트에서 검증 | NFR-2.5 | PASS |

¹ 로컬 브로커 기준. LTE 왕복 지연(수십~수백 ms)을 더해도 목표 여유 있음 —
실망 실측은 로봇 파일럿 단계 항목.

## 파이프라인별 상세

| 파이프라인 | 수신 | p50 | p95 | max |
|---|---|---|---|---|
| odom (rate 2Hz, cdr_zstd) | 115건 | 0.33 ms | 0.51 ms | 1.03 ms |
| imu (rate 5Hz, cdr_zstd) | 253건 | 0.34 ms | 0.49 ms | 41.42 ms |
| front_cam_preview (0.5fps jpeg) | 30건 | 0.36 ms | 0.51 ms | 26.50 ms |
| lidar_preview (0.2Hz voxel) | 12건 | 0.60 ms | 1.58 ms | 1.58 ms |
| front_cam_snapshot (온디맨드) | 1건 | 0.89 ms | — | — |

max 수십 ms 스파이크는 Bulk 인코딩과의 일시적 경합 — p95 기준 1 ms 미만으로 안정.

## NFR-3 신뢰성 (참조)

- 단절 5분 → 복구 이벤트 손실 0건: `tests/integration/m4_disconnect_test.sh` (06 문서 M4 증빙)
- 재연결 시간: 5.6 s (요구 ≤ 10 s, NFR-3.2)
- 72h 연속 운영(NFR-3.4): `tools/soak_test.sh` 준비 완료 — 실행은 별도 일정
  (짧은 검증: `bash tools/soak_test.sh 1`)
