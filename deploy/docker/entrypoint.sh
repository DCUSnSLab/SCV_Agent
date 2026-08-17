#!/usr/bin/env bash
# 가상 차량 컨테이너 진입점 — ROS 환경 source 후 인자 실행.
set -eo pipefail

# ROS 의 setup.bash 는 AMENT_TRACE_SETUP_FILES 등 미정의 변수를 참조한다.
# `set -u` 상태로 소싱하면 여기서 죽으므로 소싱 구간에서만 해제한다.
set +u
source /opt/ros/humble/setup.bash
source /ws/install/setup.bash
set -u

: "${ROBOT_ID:?ROBOT_ID 가 필요합니다 (예: r01)}"
: "${MQTT_HOST:=broker}"
export MQTT_HOST

echo "[entrypoint] ROBOT_ID=${ROBOT_ID} MQTT_HOST=${MQTT_HOST} CONFIG=${FTA_CONFIG:-/opt/fta/config/r01.yaml}"
echo "[entrypoint] BAG=${BAG_PATH:-(없음)}"

exec "$@"
