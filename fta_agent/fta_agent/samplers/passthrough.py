"""passthrough 샘플러 — 무가공 통과 (비주기 발행 토픽 등)."""
from __future__ import annotations

from fta_agent.core.message_view import MessageView
from fta_agent.core.registry import SAMPLER_REGISTRY
from fta_agent.samplers.base import Decision, ISampler


@SAMPLER_REGISTRY.register("passthrough")
class PassthroughSampler(ISampler):
    def decide(self, msg: MessageView, now: float) -> Decision:
        return Decision.PASS
