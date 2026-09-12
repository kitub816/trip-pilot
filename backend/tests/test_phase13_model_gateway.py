from types import SimpleNamespace

import httpx
import pytest

from app.errors import ModelCallBudgetExceeded, ModelRateLimit, UpstreamTimeout
from app.services.llm_service import ModelGateway


def test_gateway_tracks_local_estimate_and_resets_per_request():
    gateway = ModelGateway(max_calls=2, max_prompt_chars=20)
    agent = SimpleNamespace(run=lambda prompt: "响应")
    gateway.begin_request()
    assert gateway.run(agent, "提示") == "响应"
    assert gateway.usage.call_count == 1
    assert gateway.usage.estimated_prompt_tokens >= 1
    gateway.begin_request()
    assert gateway.usage.call_count == 0


def test_gateway_blocks_extra_calls_and_oversized_prompt_before_provider():
    gateway = ModelGateway(max_calls=1, max_prompt_chars=3)
    agent = SimpleNamespace(run=lambda prompt: "ok")
    gateway.run(agent, "abc")
    with pytest.raises(ModelCallBudgetExceeded):
        gateway.run(agent, "x")
    gateway.begin_request()
    with pytest.raises(ModelCallBudgetExceeded):
        gateway.run(agent, "toolong")


def test_gateway_classifies_rate_limit_and_timeout_without_leaking_text():
    response = SimpleNamespace(status_code=429)
    rate_limited = SimpleNamespace(run=lambda _: (_ for _ in ()).throw(httpx.HTTPStatusError(
        "secret", request=httpx.Request("GET", "https://example.test"), response=response,
    )))
    with pytest.raises(ModelRateLimit):
        ModelGateway(1, 10).run(rate_limited, "x")
    slow = SimpleNamespace(run=lambda _: (_ for _ in ()).throw(TimeoutError("secret")))
    with pytest.raises(UpstreamTimeout):
        ModelGateway(1, 10).run(slow, "x")
