import socket
import pytest
from app.config import Settings, get_settings
from app.services.retrieval_service import TripRetrievalResult
from app.workflows import trip_workflow

@pytest.fixture(autouse=True)
def offline_settings(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_ID", "LLM_TIMEOUT", "AMAP_API_KEY", "UNSPLASH_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_MODEL_ID", "test-model")
    monkeypatch.setenv("AMAP_API_KEY", "test-map-secret")
    get_settings.cache_clear()
    original_connect = socket.socket.connect
    def deny_network(sock, address):
        # Windows asyncio implements socketpair using a loopback connection.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        raise AssertionError("External network is forbidden in offline tests")
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(
        trip_workflow, "retrieve_trip_context",
        lambda constraints: TripRetrievalResult((), (), (), ()),
    )
    yield
    get_settings.cache_clear()
