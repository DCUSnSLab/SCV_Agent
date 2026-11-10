# SCV_Agent

차량의 모니터링 agent다. ROS 2 토픽을 골라 줄이고 압축해서 서버로 보내고, 서버가 보낸 명령을 검사한 뒤 실행한다. 전송은 [tierlink](https://github.com/nevlife/tierlink)의 monitor 등급을 쓴다. 원격제어(teleop)가 쓰고 남은 대역폭만 쓰고, 큐가 쌓이면 먼저 줄인다.

이 브랜치(`jazzy`)는 ROS 2 Jazzy용 C++ 컴포넌트로 새로 만드는 중이다. 이전 Python 구현(FTA, MQTT)과 요구사항, 설계 문서는 `main` 브랜치에 있다.

## 구성

| 파일 | 역할 |
| --- | --- |
| `src/agent.hpp` | 컴포넌트 `fleet_telemetry::Agent`. 스트림을 받아 보내고, 명령을 실행한다 |
| `src/agent_config.hpp` | 스트림 선언과 명령 레지스트리를 YAML에서 읽는다 |
| `src/command_gate.hpp` | 명령 형식과 검사(등록 여부, TTL, `cmd_id` 중복) |
| `src/rate_gate.hpp` | 스트림마다 정한 주기로 거른다. 복사하기 전에 거르므로 고주기 토픽의 비용이 보내는 주기에 비례한다 |
| `src/zstd_codec.hpp` | 원본 CDR을 zstd로 압축한다 |
| `src/send_command_main.cpp` | `send_command`. 명령 하나를 보내고 응답을 출력하는 디버깅 도구 |

## 동작

- 스트림은 `config/streams.yaml`에 적는다. 토픽마다 이름, 타입, delivery(`latest`, `reliable`, `frame`), 주기(`rate_hz`)를 정한다. agent는 토픽을 원본 CDR로 받아(`GenericSubscription`) 주기로 거르고 zstd로 압축한 뒤 monitor 등급으로 보낸다. 서버가 타입을 알 수 있게 스트림 목록(`catalog`)을 주기마다 보낸다. 한 줄이 스트림 하나이고, 이름, 타입, 토픽, delivery를 탭으로 나눠 적는다.
- 보내는 양은 agent 자신의 조절기(`Aimd`)가 정한다. teleop_epoch의 `teleop_video`가 모니터링 예산(`allowance`)을 발행하는 동안에는 그 값을 상한으로 쓴다. 예산이 `link.allowance_expires_ms` 동안 오지 않으면 상한을 푼다.
- 서버 명령은 `streams.yaml`의 `commands`에 등록한 토픽에만 발행된다. 명령에는 TTL이 있어야 하고(최대 `command.max_ttl_ms`), 같은 `cmd_id`는 한 번만 실행된다. 결과(`done`, `unknown`, `expired`, `duplicate`, `invalid`)는 `result`로 돌려보낸다. 원격 정지는 `/teleop/stop`(`std_msgs/msg/Empty`)을 등록해 두는 것으로 처리한다. teleop_epoch의 `teleop_control`이 이 토픽을 받아 운전을 멈춘다.

```bash
ros2 launch fleet_telemetry fleet_telemetry.launch.py [streams_file:=<file>.yaml]
send_command tcp/<server>:7447 scv/r01 stop 2000 0001000000   # std_msgs/Empty의 CDR
```

## 빌드와 시험

```bash
colcon build --symlink-install --packages-select fleet_telemetry
colcon test --packages-select fleet_telemetry
colcon test-result --test-result-base build/fleet_telemetry
```

아직 없는 것: 이미지와 PCD 스트림(JPEG, voxel), 필드 값으로 거르는 샘플러(deadband, event), agent 자신의 상태(health) 스트림.

