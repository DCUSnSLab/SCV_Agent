# 통합 테스트 공통 헬퍼 — bash에서 source 하여 사용 (이슈 A-5)
#
# 잔존 FTA 프로세스는 동일 client_id(fta-{robot_id})로 브로커 세션을 서로 킥하여
# 테스트 전 항목을 오탐 실패시킨다. 원인 추적이 어려우므로 시작 전에 차단하고,
# 종료 후에도 남았는지 확인한다.

# argv[1]이 아래 실행 파일로 끝나는 프로세스만 FTA 프로세스로 판정한다.
# `pgrep -f <패턴>` 만으로는 같은 문자열을 포함한 셸 명령줄(테스트를 호출한 셸 자신 등)까지
# 잡혀 오탐이 난다.
_FTA_EXECS="lib/fta_agent/agent lib/fta_tools/test_receiver"

_fta_stray() {  # 잔존 프로세스를 "PID CMD" 형식으로 출력 (없으면 아무것도 출력 안 함)
  local pid argv1 exec_name
  for pid in $(pgrep -f "lib/fta_agent/agent|lib/fta_tools/test_receiver" 2>/dev/null); do
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "$PPID" ] && continue
    [ -r "/proc/$pid/cmdline" ] || continue
    argv1=$(tr '\0' '\n' < "/proc/$pid/cmdline" | sed -n 2p)
    for exec_name in $_FTA_EXECS; do
      case "$argv1" in
        */$exec_name) echo "$pid $(tr '\0' ' ' < "/proc/$pid/cmdline")" ;;
      esac
    done
  done
}

fta_preflight() {  # fta_preflight <테스트이름>
  local stray
  stray=$(_fta_stray)
  [ -z "$stray" ] && return 0
  echo "[$1] 중단: FTA 프로세스가 이미 실행 중입니다 — 종료 후 다시 실행하세요."
  echo "$stray" | sed 's/^/  /'
  exit 2
}

fta_check_leftover() {
  local left
  left=$(_fta_stray)
  [ -z "$left" ] && return 0
  echo "  경고: 종료 후에도 FTA 프로세스 잔존 (다음 실행이 오탐 실패할 수 있음) —"
  echo "$left" | sed 's/^/    /'
}

fta_count() {  # fta_count <패턴> <파일> — 매치 0건·파일 없음 모두 0 을 반환 (이슈 A-2)
  local n                       # `grep -c ... || echo 0` 은 "0\n0" 을 만들어
  n=$(grep -c -- "$1" "$2" 2>/dev/null)   # `[: integer expression expected` 를 유발한다
  echo "${n:-0}"
}
