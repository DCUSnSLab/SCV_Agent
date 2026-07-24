"""문자열 키 → 구현 클래스 레지스트리.

Sampler / Codec / Transport 공용. 설정 YAML의 ``type:`` 값이 여기 등록된
키와 매칭된다. 새 전략 추가 = 클래스 작성 + @register 데코레이터 한 줄.
구체 클래스를 직접 참조하는 코드는 금지 (아키텍처 불변 조건 1).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Type


class RegistryError(Exception):
    pass


class Registry:
    def __init__(self, kind: str):
        self._kind = kind
        self._entries: Dict[str, Type[Any]] = {}

    @property
    def kind(self) -> str:
        return self._kind

    def register(self, key: str) -> Callable[[Type[Any]], Type[Any]]:
        def decorator(cls: Type[Any]) -> Type[Any]:
            if key in self._entries:
                raise RegistryError(
                    f"{self._kind} 레지스트리에 '{key}'가 이미 등록되어 있습니다"
                    f" ({self._entries[key].__name__})"
                )
            self._entries[key] = cls
            return cls

        return decorator

    def create(self, key: str, **params: Any) -> Any:
        if key not in self._entries:
            raise RegistryError(
                f"알 수 없는 {self._kind} 타입 '{key}'. "
                f"사용 가능: {sorted(self._entries)}"
            )
        return self._entries[key](**params)

    def keys(self):
        return sorted(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries


SAMPLER_REGISTRY = Registry("sampler")
CODEC_REGISTRY = Registry("codec")
TRANSPORT_REGISTRY = Registry("transport")
