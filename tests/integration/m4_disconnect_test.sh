#!/bin/bash
# M4 단절 자동화 테스트 (NFR-3.1): 브로커 차단 CUT_SEC초 → 복구 → 이벤트 손실 0건 검증
#
# 사용: bash tests/integration/m4_disconnect_test.sh [CUT_SEC] [WORK_DIR]
#   CUT_SEC  차단 시간 (기본 300 = 완료 기준 5분)
#   WORK_DIR 산출물 디렉토리 (기본 /tmp/fta_m4_test)
set -o pipefail
CUT_SEC=${1:-300}
WORK=${2:-/tmp/fta_m4_test}
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

cd "$REPO"
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=42   # 동시 실행 중인 다른 테스트와 DDS 격리

rm -rf "$WORK"; mkdir -p "$WORK/buffer"
echo "[m4-test] 산출물: $WORK, 차단 시간: ${CUT_SEC}s"

start_broker() {
  /usr/sbin/mosquitto -p 18883 > "$WORK/broker.log" 2>&1 &
  BROKER_PID=$!
  sleep 1
}

start_broker
/usr/bin/python3 install/fta_tools/lib/fta_tools/test_receiver \
  --port 18883 --out "$WORK/received.jsonl" > "$WORK/receiver.log" 2>&1 &
RECV_PID=$!

export ROBOT_ID=r01 FTA_BUFFER_DIR="$WORK/buffer"
/usr/bin/python3 install/fta_agent/lib/fta_agent/agent \
  --config fta_agent/config/fta_m4_test.yaml > "$WORK/agent.log" 2>&1 &
AGENT_PID=$!

/usr/bin/python3 tests/integration/counter_publisher.py --rate 2 > "$WORK/publisher.log" 2>&1 &
PUB_PID=$!

echo "[m4-test] 평시 10초..."
sleep 10

echo "[m4-test] 브로커 차단 (${CUT_SEC}s)"
kill $BROKER_PID; wait $BROKER_PID 2>/dev/null
CUT_START=$(date +%s)
sleep "$CUT_SEC"

echo "[m4-test] 브로커 복구"
start_broker
RECOVER_START=$(date +%s)

# 재연결(백오프 최대 30s) + drain + 평시 복귀 확인
sleep 40

kill $PUB_PID $AGENT_PID $RECV_PID $BROKER_PID 2>/dev/null
sleep 2

echo "[m4-test] 결과 분석"
/usr/bin/python3 - "$WORK" "$CUT_START" "$RECOVER_START" << 'EOF'
import json, sys
from collections import defaultdict

work, cut_start, recover_start = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
recs = [json.loads(l) for l in open(f"{work}/received.jsonl")]
by = defaultdict(list)
for r in recs:
    by[r["pipeline"]].append(r)

counters = sorted({r["payload"]["data"] for r in by["event_counter"]})
expected = list(range(max(counters) + 1)) if counters else []
missing = sorted(set(expected) - set(counters))
dup = len(by["event_counter"]) - len(counters)

cut_events = [c for c in counters
              for r in [next(x for x in by["event_counter"] if x["payload"]["data"] == c)]
              if cut_start <= r["stamp_agent"] <= recover_start]

reconnect_delay = None
post = [r for r in recs if r["recv_time"] >= recover_start]
if post:
    reconnect_delay = min(r["recv_time"] for r in post) - recover_start

print(f"이벤트 수신: 고유 {len(counters)}건 (중복 재전송 {dup}건 — QoS1 at-least-once 허용)")
print(f"기대 범위: 0~{max(counters) if counters else '-'}")
print(f"결손: {missing if missing else '없음'}")
print(f"단절 구간(stamp_agent 기준) 발생 이벤트: {len(cut_events)}건 — 복구 후 전달 확인")
print(f"복구→첫 수신: {reconnect_delay:.1f}s" if reconnect_delay is not None else "복구 후 수신 없음!")
odom = by.get("odom", [])
print(f"상태(odom) 수신: {len(odom)}건")

ok = not missing and len(cut_events) > 0 and reconnect_delay is not None
print("\n결과: " + ("PASS — 이벤트 손실 0건 (NFR-3.1 충족)" if ok else "FAIL"))
sys.exit(0 if ok else 1)
EOF
RESULT=$?
echo "[m4-test] 종료 코드: $RESULT"
exit $RESULT
