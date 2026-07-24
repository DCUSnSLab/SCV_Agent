import textwrap

import pytest
import yaml

# 플러그인 자기등록 (레지스트리 교차 검증용)
import fta_agent.samplers  # noqa: F401
import fta_agent.codecs  # noqa: F401
import fta_agent.transports  # noqa: F401

from fta_agent.config.loader import ConfigError, load_config

VALID = textwrap.dedent("""
    agent:
      robot_id: ${ROBOT_ID}
    transport:
      type: mqtt
      mqtt: { host: localhost, port: 1883 }
    pipelines:
      - name: odom
        topic: /odom
        msg_type: nav_msgs/msg/Odometry
        sampler: { type: passthrough }
        codec: { type: cbor }
        priority: high
""")


def write(tmp_path, content):
    p = tmp_path / "cfg.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_valid_config_with_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_ID", "r01")
    cfg = load_config(write(tmp_path, VALID))
    assert cfg["agent"]["robot_id"] == "r01"
    assert cfg["pipelines"][0]["name"] == "odom"


def test_missing_env_var_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("ROBOT_ID", raising=False)
    with pytest.raises(ConfigError, match="ROBOT_ID"):
        load_config(write(tmp_path, VALID))


def test_unknown_sampler_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_ID", "r01")
    bad = VALID.replace("type: passthrough", "type: no_such_sampler")
    with pytest.raises(ConfigError, match="no_such_sampler"):
        load_config(write(tmp_path, bad))


def test_unknown_codec_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_ID", "r01")
    bad = VALID.replace("type: cbor", "type: no_such_codec")
    with pytest.raises(ConfigError, match="no_such_codec"):
        load_config(write(tmp_path, bad))


def test_missing_required_field_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_ID", "r01")
    bad = VALID.replace("    priority: high\n", "")
    with pytest.raises(ConfigError, match="priority"):
        load_config(write(tmp_path, bad))


def test_invalid_priority_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_ID", "r01")
    bad = VALID.replace("priority: high", "priority: urgent")
    with pytest.raises(ConfigError, match="priority|urgent"):
        load_config(write(tmp_path, bad))


def test_duplicate_pipeline_name_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_ID", "r01")
    cfg = yaml.safe_load(VALID)
    cfg["pipelines"].append(dict(cfg["pipelines"][0], topic="/odom2"))
    with pytest.raises(ConfigError, match="중복"):
        load_config(write(tmp_path, yaml.safe_dump(cfg)))


def test_missing_file_fails():
    with pytest.raises(ConfigError, match="설정 파일"):
        load_config("/nonexistent/path.yaml")
