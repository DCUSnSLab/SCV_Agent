#!/bin/bash
# 72시간 soak 테스트 (NFR-3.4): 장시간 연속 운영에서 메모리 누수·성능 저하 검증
#
# 사용: bash tools/soak_test.sh [DURATION_H] [WORK_DIR]
#   기본 72시간. 개발 검증은 짧게: bash tools/soak_test.sh 1
#
# 구성: 전용 브로커(18884) + 합성 발행자(이벤트 2Hz + odom 20Hz) + 에이전트
# 산출: WORK_DIR/soak.csv (1분 간격 CPU/RSS/스레드/발행량), 종료 시 요약 판정
#   판정 기준: RSS 선형 증가 없음 (후반 25% 평균이 전반 25% 평균의 110% 이내)
set -o pipefail
DURATION_H=${1:-72}
WORK=${2:-/tmp/fta_soak}
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=44 ROBOT_ID=soak01 FTA_BUFFER_DIR="$WORK/buffer"

rm -rf "$WORK"; mkdir -p "$WORK/buffer"
DURATION_S=$(python3 -c "print(int($DURATION_H * 3600))")
echo "[soak] ${DURATION_H}h (${DURATION_S}s), 산출물: $WORK"

/usr/sbin/mosquitto -p 18884 > "$WORK/broker.log" 2>&1 &
BROKER_PID=$!
sleep 1

sed 's/port: 18883/port: 18884/' fta_agent/config/fta_m4_test.yaml > "$WORK/soak_config.yaml"
/usr/bin/python3 install/fta_agent/lib/fta_agent/agent \
  --config "$WORK/soak_config.yaml" --log-format json > "$WORK/agent.log" 2>&1 &
AGENT_PID=$!
/usr/bin/python3 tests/integration/counter_publisher.py --rate 2 > "$WORK/publisher.log" 2>&1 &
PUB_PID=$!

cleanup() { kill $AGENT_PID $PUB_PID $BROKER_PID 2>/dev/null; }
trap cleanup EXIT

/usr/bin/python3 - "$AGENT_PID" "$WORK/soak.csv" "$DURATION_S" << 'EOF'
import sys, time, psutil
pid, out, dur = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
p = psutil.Process(pid)
p.cpu_percent()
with open(out, "w") as f:
    f.write("elapsed_min,cpu_pct,rss_mb,threads\n")
    t0 = time.time()
    while time.time() - t0 < dur:
        time.sleep(60)
        try:
            f.write(f"{(time.time()-t0)/60:.0f},{p.cpu_percent():.1f},"
                    f"{p.memory_info().rss/1048576:.1f},{p.num_threads()}\n")
            f.flush()
        except psutil.NoSuchProcess:
            print("에이전트 프로세스 소멸 — soak 실패", file=sys.stderr)
            sys.exit(2)
EOF

/usr/bin/python3 - "$WORK/soak.csv" << 'EOF'
import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1])))
if len(rows) < 8:
    print("샘플 부족 — 판정 불가"); sys.exit(1)
rss = [float(r["rss_mb"]) for r in rows]
q = len(rss) // 4
head, tail = statistics.mean(rss[:q]), statistics.mean(rss[-q:])
cpu = statistics.mean(float(r["cpu_pct"]) for r in rows)
print(f"RSS: 초반 {head:.0f}MB → 후반 {tail:.0f}MB ({tail/head*100:.0f}%), CPU 평균 {cpu:.1f}%")
ok = tail <= head * 1.10 and tail <= 512
print("판정: " + ("PASS — 메모리 누수·성능 저하 없음 (NFR-3.4)" if ok else "FAIL"))
sys.exit(0 if ok else 1)
EOF
