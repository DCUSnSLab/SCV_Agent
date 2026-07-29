#!/bin/bash
# M6 성능 테스트 (NFR-1/NFR-2): rosbag 재생 + 에이전트 리소스 샘플링 + 지연 분석
# 사용: bash tests/integration/m6_perf_test.sh [PLAY_SEC] [WORK_DIR]
set -o pipefail
PLAY_SEC=${1:-60}
WORK=${2:-/tmp/fta_m6_perf}
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
source /opt/ros/humble/setup.bash
source install/setup.bash
source tests/integration/common.sh
export ROS_DOMAIN_ID=43

fta_preflight m6-test    # 잔존 프로세스가 리소스 측정을 오염시키므로 사전 차단 (A-5)

rm -rf "$WORK"; mkdir -p "$WORK"
export ROBOT_ID=r01

cleanup() { kill $MON_PID $AGENT_PID $RECV_PID $BAGPID 2>/dev/null; }
trap cleanup EXIT        # 어떤 경로로 종료하든 자식 정리 (A-5)

/usr/bin/python3 install/fta_tools/lib/fta_tools/test_receiver \
  --out "$WORK/received.jsonl" > "$WORK/receiver.log" 2>&1 &
RECV_PID=$!
/usr/bin/python3 install/fta_agent/lib/fta_agent/agent \
  --config fta_agent/config/fta_bag_replay.yaml > "$WORK/agent.log" 2>&1 &
AGENT_PID=$!
sleep 3

# 리소스 샘플러 (1초 간격 CSV)
/usr/bin/python3 - "$AGENT_PID" "$WORK/resource.csv" "$((PLAY_SEC + 10))" << 'EOF' &
import sys, time, psutil
pid, out, dur = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
p = psutil.Process(pid)
p.cpu_percent()
with open(out, "w") as f:
    f.write("t,cpu_pct,rss_mb\n")
    t0 = time.time()
    while time.time() - t0 < dur:
        time.sleep(1)
        try:
            f.write(f"{time.time()-t0:.0f},{p.cpu_percent():.1f},"
                    f"{p.memory_info().rss/1048576:.1f}\n")
            f.flush()
        except psutil.NoSuchProcess:
            break
EOF
MON_PID=$!

timeout "$PLAY_SEC" ros2 bag play ~/data/rosbag2_2026_01_21-18_41_02 \
  --topics /odom_bae /vectornav/imu /camera/camera/color/image_raw /velodyne_points \
  > /dev/null 2>&1 &
BAGPID=$!
sleep $((PLAY_SEC / 2))
SNAP_T0=$(/usr/bin/python3 -c "import time; print(time.time())")
ros2 service call /fta/request_snapshot/front_cam_snapshot std_srvs/srv/Trigger > /dev/null 2>&1
wait $BAGPID 2>/dev/null
sleep 3
cleanup
sleep 1
fta_check_leftover

/usr/bin/python3 - "$WORK" "$SNAP_T0" << 'EOF'
import csv, json, statistics, sys
from collections import defaultdict

work, snap_t0 = sys.argv[1], float(sys.argv[2])
recs = [json.loads(l) for l in open(f"{work}/received.jsonl")]
by = defaultdict(list)
for r in recs:
    by[r["pipeline"]].append(r)

print("=== 지연 (에이전트 처리→수신, ms) ===")
for name, rs in sorted(by.items()):
    lat = sorted(r["latency_ms"] for r in rs)
    p50 = lat[len(lat)//2]; p95 = lat[int(len(lat)*0.95)] if len(lat) > 1 else lat[0]
    print(f"  {name:20s} n={len(rs):4d}  p50={p50:6.2f}  p95={p95:6.2f}  max={lat[-1]:6.2f}")

snap = by.get("front_cam_snapshot", [])
if snap:
    print(f"\n스냅샷 요청→수신: {snap[0]['recv_time'] - snap_t0:.2f}s (NFR-2.4 목표 3s)")

rows = list(csv.DictReader(open(f"{work}/resource.csv")))
cpu = [float(r["cpu_pct"]) for r in rows]
rss = [float(r["rss_mb"]) for r in rows]
print(f"\n=== 리소스 (NFR-1) ===")
print(f"  CPU: 평균 {statistics.mean(cpu):.1f}%  p95 {sorted(cpu)[int(len(cpu)*0.95)]:.1f}%  최대 {max(cpu):.1f}%  (상한 20%/1코어)")
print(f"  RSS: 평균 {statistics.mean(rss):.0f}MB  최대 {max(rss):.0f}MB  (상한 512MB)")

total_bytes = sum(r["payload_size"] for r in recs)
span = max(r["recv_time"] for r in recs) - min(r["recv_time"] for r in recs)
print(f"\n총 업링크: {total_bytes*8/span/1000:.0f} kbps (상한 1000)")
EOF
echo "[m6-perf] 완료 — 산출물 $WORK"
