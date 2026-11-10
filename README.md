# SCV_Agent

차량의 모니터링 agent다. ROS 2 토픽을 골라 줄이고 압축해서 서버로 보내고, 서버가 보낸 명령을 검사한 뒤 실행한다. 전송은 [tierlink](https://github.com/nevlife/tierlink)의 monitor 등급을 쓴다. 원격제어(teleop)가 쓰고 남은 대역폭만 쓰고, 큐가 쌓이면 먼저 줄인다.

이 브랜치(`jazzy`)는 ROS 2 Jazzy용 C++ 컴포넌트로 새로 만드는 중이다. 이전 Python 구현(FTA, MQTT)과 요구사항, 설계 문서는 `main` 브랜치에 있다.
