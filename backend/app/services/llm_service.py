"""Existing HelloAgents client with explicit settings and shutdown cleanup."""
from threading import Lock
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from ..config import get_settings
from ..errors import (ModelCallBudgetExceeded, ModelRateLimit, upstream_failure,
                      ConfigurationError, AppError)

if TYPE_CHECKING:
    from hello_agents import HelloAgentsLLM

_llm_instance: "HelloAgentsLLM | None" = None
_lock = Lock()

class RunnableAgent(Protocol):
    def run(self, prompt: str) -> str: ...

@dataclass(frozen=True)
class ModelUsage:
    call_count: int
    estimated_prompt_tokens: int
    estimated_completion_tokens: int

class ModelGateway:
    """Per-planning-request budget and safe error boundary around HelloAgents."""
    def __init__(self, max_calls: int, max_prompt_chars: int) -> None:
        self._max_calls = max_calls
        self._max_prompt_chars = max_prompt_chars
        self._call_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def begin_request(self) -> None:
        self._call_count = self._prompt_tokens = self._completion_tokens = 0

    @property
    def usage(self) -> ModelUsage:
        return ModelUsage(self._call_count, self._prompt_tokens, self._completion_tokens)

    def run(self, agent: RunnableAgent, prompt: str) -> str:
        if len(prompt) > self._max_prompt_chars or self._call_count >= self._max_calls:
            raise ModelCallBudgetExceeded()
        self._call_count += 1
        self._prompt_tokens += self._estimate_tokens(prompt)
        try:
            response = agent.run(prompt)
        except AppError:
            raise
        except Exception as exc:
            raise self._classify(exc) from exc
        if not isinstance(response, str):
            raise upstream_failure(TypeError("model response must be text"))
        self._completion_tokens += self._estimate_tokens(response)
        return response

    @staticmethod
    def _estimate_tokens(value: str) -> int:
        return max(1, (len(value) + 3) // 4)

    @staticmethod
    def _classify(exc: BaseException) -> AppError:
        if getattr(getattr(exc, "response", None), "status_code", None) == 429:
            return ModelRateLimit()
        return upstream_failure(exc)

def create_model_gateway() -> ModelGateway:
    settings = get_settings()
    return ModelGateway(settings.llm_max_calls_per_plan, settings.llm_max_prompt_chars)

def get_llm() -> "HelloAgentsLLM":
    global _llm_instance
    with _lock:
        if _llm_instance is None:
            settings = get_settings()
            if not settings.llm_api_key.get_secret_value().strip() or not settings.llm_model.strip():
                raise ConfigurationError()
            try:
                from hello_agents import HelloAgentsLLM
                _llm_instance = HelloAgentsLLM(api_key=settings.llm_api_key.get_secret_value(),
                    base_url=settings.llm_base_url, model=settings.llm_model,
                    timeout=settings.llm_timeout, provider="custom")
            except Exception as exc:
                raise upstream_failure(exc) from exc
        return _llm_instance

def reset_llm() -> None:
    """Call only after active planner requests have drained."""
    global _llm_instance
    with _lock:
        instance, _llm_instance = _llm_instance, None
        if instance is not None:
            # HelloAgents 0.2.9 has no public close; isolate SDK-private access here.
            instance._client.close()
