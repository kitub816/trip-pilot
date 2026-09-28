"""Amap calls must not inherit workstation proxies that break provider TLS."""
from app.services.tool_runtime import AMAP_API_HOST, amap_child_env


def test_amap_child_environment_forces_provider_direct(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,example.com")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")

    child = amap_child_env("fixture-key")

    assert child["AMAP_MAPS_API_KEY"] == "fixture-key"
    assert child["NO_PROXY"] == child["no_proxy"]
    assert set(child["NO_PROXY"].split(",")) == {
        "localhost", "example.com", AMAP_API_HOST,
    }
    assert "HTTP_PROXY" not in child and "HTTPS_PROXY" not in child


def test_amap_child_environment_does_not_duplicate_provider(monkeypatch):
    monkeypatch.setenv("NO_PROXY", f"localhost,{AMAP_API_HOST}")
    monkeypatch.delenv("no_proxy", raising=False)

    child = amap_child_env("fixture-key")

    assert child["NO_PROXY"].split(",").count(AMAP_API_HOST) == 1
