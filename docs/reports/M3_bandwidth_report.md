# M3 대역폭 측정 리포트

- 측정일: 2026-07-24
- 방법: `~/data/rosbag2_2026_01_21-18_41_02` 재생 (40초 구간, `--topics` 4종) →
  `fta_bag_replay.yaml` 파이프라인 → 로컬 mosquitto → 테스트 리시버 jsonl 분석
- 환경: 개발 머신 로컬 (네트워크 지연 미포함 — 종단 지연은 에이전트 처리 지연 기준)

## 파이프라인별 측정 결과

| 파이프라인 | 원 데이터 | 전송 정책 | 수신 | 평균 payload | 실효 대역폭 | 평균 지연 |
|---|---|---|---|---|---|---|
| odom | 50 Hz × 724 B | rate 2Hz + cdr_zstd | 76건 | 125 B | **2.0 kbps** | 0.36 ms |
| imu | 20 Hz × 324 B | rate 5Hz + cdr_zstd | 166건 | 134 B | **4.6 kbps** | 0.60 ms |
| front_cam_preview | 30 Hz × 1,354,824 B | rate 0.5Hz + jpeg(q60, 640px) | 20건 | 29,376 B | **122.8 kbps** | 0.83 ms |
| front_cam_snapshot | (온디맨드) | on_demand + jpeg(q85, 원본 크기) | 1건 | 73,602 B | 요청 시 1회 | 0.71 ms |
| lidar_preview | 10 Hz × 1,275,841 B | rate 0.2Hz + voxel(0.2m)+zstd | 5건 | ~21,000 B | **~34 kbps** | <1 ms |
| lidar_snapshot | (온디맨드) | on_demand + voxel(0.1m)+zstd | 1건 | 54,556 B | 요청 시 1회 | <1 ms |

## 압축·감축 효율

| 데이터 | 원본 | 전송 | 감축률 |
|---|---|---|---|
| Odometry CDR | 724 B | zstd 125 B | **17%로 압축** |
| Imu CDR | 324 B | zstd 134 B | 42%로 압축 |
| 카메라 프레임 | 1,354,824 B (rgb8 원본) | JPEG q60/640px 29,376 B | **2.2%** |
| LiDAR 프레임 | 1,275,841 B (~30,000점) | voxel 0.2m 1,700~2,500점 ~21 KB | **1.6%** |

## NFR-2.1 대비 평가

- 상태 데이터(odom+imu) 합계: **~6.6 kbps** — 목표(평균 100~300kbps, 상한 1Mbps) 대비 매우 여유
- 카메라 프리뷰 0.5fps 포함 시: **~130 kbps** — 목표 구간 내
- LiDAR 프리뷰 0.2Hz 포함 시: **~164 kbps** — 목표 구간 내
- 정책 없이 원본 전송 시 카메라 단독 **325 Mbps**, LiDAR 단독 **102 Mbps** → 샘플링+코덱 정책이 필수임을 실측으로 확인

## 발견 사항

- `read_points_numpy`는 혼합 dtype 필드(Velodyne: x/y/z/intensity/ring/time)에서 실패 →
  구조화 배열 `read_points` 방식으로 수정 (커밋 참조)
- 온디맨드 스냅샷 요청→수신 소요: 재생 프레임 주기 이내 (NFR-2.4 3초 대비 여유). 실망(LTE) 검증은 파일럿에서
- 수신 jsonl과 저장된 JPEG 파일 정상 디코딩 확인 (`--save-bulk`)
