# 가상 차량 컨테이너 — bag 재생 + GPS shim + FTA 에이전트 (개발·검증용)
#
# 빌드 컨텍스트는 저장소 루트다:
#   docker build -f deploy/docker/Dockerfile -t fta-vehicle:dev .
#
# 운영 배포는 이 이미지가 아니라 deploy/fta_agent.service (systemd) 를 쓴다 —
# 이 이미지는 rosbag 재생기와 GPS 합성기를 품고 있어 실차에 올리면 안 된다.
FROM ros:humble-ros-base

SHELL ["/bin/bash", "-c"]

# --- 런타임 의존 ---------------------------------------------------------
# python3-opencv: jpeg 코덱 / sensor-msgs-py: voxel_zstd 코덱의 point_cloud2
# paho-mqtt 는 반드시 2.x — 1.x 에는 CallbackAPIVersion 이 없어 전송이 기동 실패한다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-opencv \
        python3-numpy \
        python3-yaml \
        python3-psutil \
        python3-jsonschema \
        ros-humble-sensor-msgs-py \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir "paho-mqtt>=2.0" cbor2 zstandard

# --- hunter_msgs (커스텀 타입) -------------------------------------------
# 없으면 ros2 bag play 가 /hunter_status 를 "package not found" 로 스킵해
# 배터리 전압·조향각·차대 상태가 통째로 빠진다. BSD, 의존은 std_msgs 뿐.
ARG HUNTER_MSGS_REPO=https://github.com/agilexrobotics/hunter_ros2.git
ARG HUNTER_MSGS_REF=humble
WORKDIR /ws
RUN git clone --depth 1 --branch ${HUNTER_MSGS_REF} ${HUNTER_MSGS_REPO} /tmp/hunter_ros2 \
    && mkdir -p src && cp -r /tmp/hunter_ros2/hunter_msgs src/hunter_msgs \
    && rm -rf /tmp/hunter_ros2

# --- FTA 빌드 ------------------------------------------------------------
# --symlink-install 금지: install 트리가 소스 트리에 런타임 의존하게 된다(배포 지침).
COPY fta_agent src/fta_agent
COPY fta_tools src/fta_tools
RUN source /opt/ros/humble/setup.bash \
    && colcon build --event-handlers console_direct+ \
    && rm -rf build log

COPY deploy/docker/launch      /opt/fta/launch
COPY deploy/docker/config      /opt/fta/config
COPY deploy/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /var/lib/fta/buffer

# DDS 를 컨테이너 밖으로 내보내지 않는다 — 컨테이너마다 네트워크 네임스페이스가
# 따로라 loopback 이 곧 격리 경계가 된다. ROS_DOMAIN_ID 를 차량마다 배정할 필요가 없다.
ENV ROS_LOCALHOST_ONLY=1 \
    RCUTILS_LOGGING_BUFFERED_STREAM=0 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["ros2", "launch", "/opt/fta/launch/virtual_vehicle.launch.py"]
