"""ConfigLoader — YAML 로드, ${ENV} 치환, 스키마·레지스트리 교차 검증 (FR-6).

검증 실패 시 ConfigError를 던진다 — 호출측(agent_node)은 즉시 종료하고
원인을 명시한다. 조용한 오동작 금지 (02 문서 §3.1).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

import jsonschema
import yaml

from fta_agent.config.schema import CONFIG_SCHEMA
from fta_agent.core.registry import CODEC_REGISTRY, SAMPLER_REGISTRY, TRANSPORT_REGISTRY

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    pass


def _substitute_env(node: Any, missing: list) -> Any:
    if isinstance(node, str):
        def repl(m):
            name = m.group(1)
            val = os.environ.get(name)
            if val is None:
                missing.append(name)
                return m.group(0)
            return val

        return _ENV_PATTERN.sub(repl, node)
    if isinstance(node, dict):
        return {k: _substitute_env(v, missing) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute_env(v, missing) for v in node]
    return node


def load_config(path: str | Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"설정 파일이 없습니다: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 파싱 실패 ({path}): {e}") from e

    missing: list = []
    cfg = _substitute_env(raw, missing)
    if missing:
        raise ConfigError(
            f"설정에 사용된 환경변수가 정의되지 않았습니다: {sorted(set(missing))}"
        )

    try:
        jsonschema.validate(cfg, CONFIG_SCHEMA)
    except jsonschema.ValidationError as e:
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise ConfigError(f"설정 스키마 위반 [{loc}]: {e.message}") from e

    # 스키마 통과 후 레지스트리 교차 검증 — 존재하지 않는 전략 타입 조기 차단
    t = cfg["transport"]["type"]
    if t not in TRANSPORT_REGISTRY:
        raise ConfigError(
            f"알 수 없는 transport 타입 '{t}'. 사용 가능: {TRANSPORT_REGISTRY.keys()}"
        )
    names = set()
    for p in cfg["pipelines"]:
        if p["name"] in names:
            raise ConfigError(f"파이프라인 이름 중복: '{p['name']}'")
        names.add(p["name"])
        if p["sampler"]["type"] not in SAMPLER_REGISTRY:
            raise ConfigError(
                f"파이프라인 '{p['name']}': 알 수 없는 sampler 타입 "
                f"'{p['sampler']['type']}'. 사용 가능: {SAMPLER_REGISTRY.keys()}"
            )
        if p["codec"]["type"] not in CODEC_REGISTRY:
            raise ConfigError(
                f"파이프라인 '{p['name']}': 알 수 없는 codec 타입 "
                f"'{p['codec']['type']}'. 사용 가능: {CODEC_REGISTRY.keys()}"
            )
    return cfg
