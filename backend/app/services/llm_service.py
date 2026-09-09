"""Existing HelloAgents client with explicit settings and shutdown cleanup."""
from threading import Lock
from typing import TYPE_CHECKING
from ..config import get_settings
from ..errors import upstream_failure, ConfigurationError, UpstreamError

if TYPE_CHECKING:
    from hello_agents import HelloAgentsLLM

_llm_instance: "HelloAgentsLLM | None" = None
_lock = Lock()

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
