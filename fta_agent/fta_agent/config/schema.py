"""설정 YAML의 JSON Schema (FR-6.3 — 기동 시 검증, 조용한 오동작 금지)."""

CONFIG_SCHEMA = {
    "type": "object",
    "required": ["agent", "transport", "pipelines"],
    "additionalProperties": False,
    "properties": {
        "downlink": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "enabled": {"type": "boolean"},
                "command_timeout_sec": {"type": "number", "exclusiveMinimum": 0},
                "audit_log": {"type": "string", "minLength": 1},
            },
        },
        "agent": {
            "type": "object",
            "required": ["robot_id"],
            "additionalProperties": False,
            "properties": {
                "robot_id": {"type": "string", "minLength": 1},
                "queue_maxlen_per_priority": {"type": "integer", "minimum": 1},
                "buffer": {
                    "type": "object",
                    "required": ["dir"],
                    "additionalProperties": False,
                    "properties": {
                        "dir": {"type": "string", "minLength": 1},
                        "max_disk_mb": {"type": "integer", "minimum": 1},
                    },
                },
                "resource": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "bandwidth_limit_kbps": {"type": "number", "exclusiveMinimum": 0},
                        "cpu_limit_pct": {"type": "number", "exclusiveMinimum": 0},
                        "mem_limit_mb": {"type": "number", "exclusiveMinimum": 0},
                    },
                },
            },
        },
        "transport": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string"},
            },
        },
        "pipelines": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name", "topic", "msg_type", "sampler", "codec", "priority"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "pattern": "^[a-zA-Z0-9_]+$"},
                    "topic": {"type": "string", "pattern": "^/"},
                    "msg_type": {
                        "type": "string",
                        "pattern": "^[a-zA-Z0-9_]+/msg/[a-zA-Z0-9_]+$",
                    },
                    "sampler": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {"type": {"type": "string"}},
                    },
                    "codec": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {"type": {"type": "string"}},
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "high", "normal", "low"],
                    },
                    "msg_class": {
                        "type": "string",
                        "enum": ["state", "event", "bulk"],
                    },
                    "enabled": {"type": "boolean"},
                    "qos": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "reliability": {
                                "type": "string",
                                "enum": ["best_effort", "reliable"],
                            },
                            "durability": {
                                "type": "string",
                                "enum": ["volatile", "transient_local"],
                            },
                            "depth": {"type": "integer", "minimum": 1},
                        },
                    },
                },
            },
        },
    },
}
