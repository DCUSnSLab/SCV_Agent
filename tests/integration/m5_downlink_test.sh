#!/bin/bash
# M5 다운링크 종단 자동화 테스트
# 완료 기준: (a) 레지스트리 등록만으로 set_goal 종단 동작
#           (b) 거부 4종(TTL 만료/중복 cmd_id/미등록/스키마 위반) 통과
set -o pipefail
WORK=${1:-/tmp/fta_m5_test}
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
source /opt/ros/humble/setup.bash
source install/setup.bash

rm -rf "$WORK"; mkdir -p "$WORK"
PASS=0; FAIL=0
check() {  # check <이름> <기대문자열> <실제출력>
  if echo "$3" | grep -q "$2"; then
    echo "  PASS: $1"; PASS=$((PASS+1))
  else
    echo "  FAIL: $1 — 기대 '$2', 실제: $3"; FAIL=$((FAIL+1))
  fi
}

# 0) 레지스트리 발행 (retained) — 에이전트 기동 전 (구독 즉시 수신 검증)
/usr/bin/python3 install/fta_tools/lib/fta_tools/registry_tool \
  --file fta_tools/config/registry_example.yaml > "$WORK/registry_pub.log" 2>&1

# 1) 에이전트 (다운링크 활성) + /goal_pose 수신 확인용 echo + 카메라 발행자
export ROBOT_ID=r01 FTA_AUDIT_LOG="$WORK/audit.jsonl"
/usr/bin/python3 install/fta_agent/lib/fta_agent/agent \
  --config fta_agent/config/fta_m5_test.yaml > "$WORK/agent.log" 2>&1 &
AGENT_PID=$!
timeout 60 ros2 topic echo /goal_pose geometry_msgs/msg/PoseStamped > "$WORK/goal_echo.log" 2>&1 &
ECHO_PID=$!
timeout 60 ros2 topic pub -r 5 /camera/image_raw sensor_msgs/msg/Image \
  "{height: 4, width: 4, encoding: mono8, step: 4, data: [$(seq -s, 16 | sed 's/,$//')]}" > /dev/null 2>&1 &
CAM_PID=$!
/usr/bin/python3 install/fta_tools/lib/fta_tools/test_receiver \
  --out "$WORK/received.jsonl" > "$WORK/receiver.log" 2>&1 &
RECV_PID=$!
sleep 5

SEND="/usr/bin/python3 tests/integration/send_command.py --robot-id r01"

echo "[1] 정상 set_goal (topic kind) — 레지스트리 등록만으로 활성화"
OUT=$($SEND --interface set_goal --payload '{"pose": {"position": {"x": 3.5, "y": -1.5}}}' --cmd-id ok1)
check "set_goal accepted" '"status": "accepted"' "$OUT"

echo "[2] 거부 시나리오 4종 (NFR-7)"
OUT=$($SEND --interface set_goal --payload '{"pose": {"position": {"x": 1, "y": 1}}}' --issued-offset -60 --ttl 10)
check "TTL 만료 → expired" '"status": "expired"' "$OUT"

OUT=$($SEND --interface set_goal --payload '{"pose": {"position": {"x": 9, "y": 9}}}' --cmd-id ok1)
check "중복 cmd_id → 재실행 없이 기존 결과" 'duplicate' "$OUT"

OUT=$($SEND --interface not_registered --payload '{}')
check "미등록 인터페이스 → rejected" '"status": "rejected"' "$OUT"

OUT=$($SEND --interface set_goal --payload '{"pose": {"position": {"x": 1}}}')
check "스키마 위반(y 누락) → rejected" '"status": "rejected"' "$OUT"

echo "[3] ttl > default_ttl 거부 (NFR-7.1)"
OUT=$($SEND --interface set_goal --payload '{"pose": {"position": {"x": 1, "y": 1}}}' --ttl 999)
check "ttl 초과 → rejected" '"status": "rejected"' "$OUT"

echo "[4] service kind — 서버발 스냅샷 온디맨드"
OUT=$($SEND --interface request_snapshot_front_cam --payload '{}' --ttl 60)
check "Trigger 서비스 done" '"status": "done"' "$OUT"
check "서비스 응답 success" 'true' "$OUT"

sleep 3
kill $AGENT_PID $ECHO_PID $CAM_PID $RECV_PID 2>/dev/null
sleep 1

echo "[5] 종단 산출물 검증"
GOAL=$(grep -c "x: 3.5" "$WORK/goal_echo.log" 2>/dev/null || echo 0)
[ "$GOAL" -ge 1 ] && { echo "  PASS: /goal_pose에 목적지 발행됨 (x=3.5)"; PASS=$((PASS+1)); } \
                  || { echo "  FAIL: /goal_pose 미수신"; FAIL=$((FAIL+1)); }

SNAP=$(grep -c '"pipeline": "front_cam_snapshot"' "$WORK/received.jsonl" 2>/dev/null || echo 0)
[ "$SNAP" -ge 1 ] && { echo "  PASS: 스냅샷 업링크 수신 ($SNAP건)"; PASS=$((PASS+1)); } \
                  || { echo "  FAIL: 스냅샷 업링크 미수신"; FAIL=$((FAIL+1)); }

UNSUP=$(grep -c "hunter_mode" "$WORK/agent.log" 2>/dev/null || echo 0)
[ "$UNSUP" -ge 1 ] && { echo "  PASS: 미지원 타입(hunter_msgs) registry_status 보고"; PASS=$((PASS+1)); } \
                   || { echo "  FAIL: 미지원 인터페이스 보고 없음"; FAIL=$((FAIL+1)); }

AUDIT=$(wc -l < "$WORK/audit.jsonl" 2>/dev/null || echo 0)
[ "$AUDIT" -ge 14 ] && { echo "  PASS: 감사 로그 $AUDIT건 기록 (NFR-7.6)"; PASS=$((PASS+1)); } \
                    || { echo "  FAIL: 감사 로그 부족 ($AUDIT건)"; FAIL=$((FAIL+1)); }

echo ""
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ] && echo "M5 완료 기준 충족" || echo "M5 검증 실패"
exit $FAIL
