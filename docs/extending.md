# FTA 확장 가이드 — Sampler / Codec / Transport 추가하기

모든 전략 컴포넌트는 **인터페이스(ABC) + 레지스트리** 패턴이다 (NFR-4.3).
새 전략 추가 = ① 클래스 작성 ② `@REGISTRY.register("키")` 한 줄 ③ 패키지
`__init__.py`에 import 추가. 설정 YAML의 `type:` 값이 레지스트리 키와 매칭되며,
**기존 코드는 수정하지 않는다.**

## 1. 새 Sampler 추가

예: N개 중 1개만 통과시키는 `decimate` 샘플러.

```python
# fta_agent/samplers/decimate.py
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import SAMPLER_REGISTRY
from fta_agent.samplers.base import Decision, ISampler


@SAMPLER_REGISTRY.register("decimate")
class DecimateSampler(ISampler):
    def __init__(self, n: int):                # YAML 파라미터가 kwargs로 주입됨
        if n < 1:
            raise ValueError(f"n은 1 이상 (입력: {n!r})")  # 기동 시 검증 (FR-6.3)
        self._n = int(n)
        self._count = 0

    def decide(self, msg: MessageView, now: float) -> Decision:
        self._count += 1
        return Decision.PASS if self._count % self._n == 1 else Decision.DROP
```

```python
# fta_agent/samplers/__init__.py 에 추가
from . import decimate  # noqa: F401
```

```yaml
# 설정에서 바로 사용 가능
sampler: { type: decimate, n: 10 }
```

규칙:
- `decide()`는 worker 스레드에서 호출된다 — 역직렬화가 필요하면
  `msg.ros_msg()` (지연 역직렬화), 필드 접근은 `fta_agent.core.field_path.get_field` 사용
- 이벤트성 데이터는 `Decision.PASS_AND_FLUSH` 반환 (즉시 전송 요구)
- 파라미터 오류는 `__init__`에서 `ValueError` — 기동 시 명확히 실패해야 한다
- `request()` 메서드를 구현하면 온디맨드 트리거 서비스가 자동 연결된다 (덕 타이핑)

## 2. 새 Codec 추가

```python
# fta_agent/codecs/my_codec.py
from fta_agent.codecs.base import EncodedPayload, ICodec
from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import CODEC_REGISTRY


@CODEC_REGISTRY.register("my_codec")
class MyCodec(ICodec):
    def __init__(self, level: int = 3):
        self._level = level

    def encode(self, msg: MessageView) -> EncodedPayload:
        data = do_something(msg.raw)           # raw CDR 접근 (typesupport 불필요)
        return EncodedPayload(data=data, encoding="my_codec")
```

- `encoding` 식별자는 수신측 디코딩 계약이다 (FR-3.3) — 테스트 리시버의
  `_decode_payload()`에 대응 디코더를 추가할 것
- 무거운 인코딩은 GIL을 해제하는 C 라이브러리(zstd, OpenCV, numpy) 사용 권장

## 3. 새 Transport 추가 (예: Zenoh, 자체 프로토콜)

`ITransport`(fta_agent/transports/base.py)를 구현하고 등록한다:

```python
@TRANSPORT_REGISTRY.register("zenoh")
class ZenohTransport(ITransport):
    def __init__(self, robot_id: str, **cfg): ...
    def connect(self): ...          # 비블로킹, outbound, 자동 재연결 내장
    def publish(self, msg_class, pipeline, data, reliability) -> bool: ...
    def subscribe(self, topic, callback): ...   # 다운링크 수신 (재연결 시 유지)
    def state(self) -> ConnState: ...
    def close(self): ...
```

계약 사항 (아키텍처 불변 조건 5):
- `connect()`/`publish()`는 **절대 무한 블로킹 금지** — 단절은 정상 상황
- `publish()`가 False를 반환하면 UplinkManager가 DiskBuffer로 보존한다
- `AT_LEAST_ONCE`는 전송 확인(ACK 상당)까지 보장한 뒤 True를 반환할 것
- 설정은 `transport: { type: zenoh, zenoh: {...} }` 형태 — `type` 키와 동명의
  하위 객체가 생성자 kwargs로 주입된다

이 추상화는 전송 프로토콜 벤치마크 연구(02 문서 §6 연구 B)의 실험 플랫폼을 겸한다.

## 4. 테스트

- 단위 테스트를 `fta_agent/test/`에 추가 (기존 `test_samplers.py` 패턴 참조 —
  ROS 비의존 테스트는 FakeView 사용)
- 종단 확인: `tests/integration/` 스크립트 패턴 참조
