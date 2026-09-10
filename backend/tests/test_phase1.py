import asyncio
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import requests
from fastapi.testclient import TestClient
from hello_agents import SimpleAgent

from app.config import Settings, get_settings, validate_config, BACKEND_DIR
from app.errors import ConfigurationError, PlanParseError, ServiceBusy, UpstreamError, UpstreamTimeout
from app.api import main
from app.api.routes import trip, map as map_routes, poi
from app.agents import trip_planner_agent as planner_module
from app.services import amap_service, llm_service, unsplash_service
from app.models.schemas import TripRequest, TripPlan
from app.logging_config import JsonFormatter, request_id

REQUEST = dict(city="上海", start_date="2026-09-10", end_date="2026-09-11", travel_days=2,
               transportation="步行", accommodation="民宿", preferences=[], free_text_input="private-user-input")
PLAN = dict(city="上海", start_date="2026-09-10", end_date="2026-09-11", days=[], overall_suggestions="test fixture")

@pytest.fixture
def client():
    with TestClient(main.create_app()) as client:
        yield client


def test_config_alias_and_environment_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-secret")
    assert Settings().llm_api_key.get_secret_value() == "test-secret"
    monkeypatch.delenv("LLM_API_KEY")
    assert Settings().llm_api_key.get_secret_value() == "legacy-secret"
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=file-secret\nLLM_MODEL_ID=file-model\n")
    assert Settings(_env_file=env).llm_api_key.get_secret_value() == "legacy-secret"
    assert "legacy-secret" not in repr(Settings())


def test_config_missing_required_values(monkeypatch):
    monkeypatch.delenv("AMAP_API_KEY")
    with pytest.raises(ConfigurationError):
        validate_config(Settings())


def test_config_does_not_load_cwd_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("LLM_MODEL_ID=wrong-model\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_MODEL_ID")
    assert Settings().llm_model == ""
    assert BACKEND_DIR.is_absolute()


def test_startup_rejects_missing_llm(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY")
    get_settings.cache_clear()
    with pytest.raises(ConfigurationError), TestClient(main.create_app()):
        pass


def test_health_does_not_initialize_dependencies(client, monkeypatch):
    monkeypatch.setattr(trip, "get_trip_planner_agent", Mock(side_effect=AssertionError("must not initialize")))
    for path in ("/health", "/api/trip/health", "/api/map/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["x-request-id"]
    assert client.get("/api/trip/health").json()["external_dependencies"] == "not_checked"


def test_request_validation_is_safe(client):
    response = client.post("/api/trip/plan", json={"city": "secret-input"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "secret-input" not in response.text


@pytest.mark.parametrize("error,status,code", [(PlanParseError(),502,"PLAN_PARSE_ERROR"),
    (UpstreamError(),502,"UPSTREAM_ERROR"), (UpstreamTimeout(),504,"UPSTREAM_TIMEOUT"),
    (ServiceBusy(),503,"SERVICE_BUSY"), (RuntimeError("test-secret"),500,"INTERNAL_ERROR")])
def test_safe_failure_contract(client, monkeypatch, error, status, code):
    monkeypatch.setattr(trip, "get_trip_planner_agent", Mock(side_effect=error))
    response = client.post("/api/trip/plan", json=REQUEST, headers={"Origin":"http://localhost:5173"})
    assert response.status_code == status
    data = response.json()
    assert data["success"] is False and data["error_code"] == code
    assert data["detail"] == data["message"]
    assert data["request_id"] == response.headers["x-request-id"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "test-secret" not in response.text


def test_success_contract_and_request_id_uniqueness(client, monkeypatch):
    monkeypatch.setattr(trip, "get_trip_planner_agent", lambda: SimpleNamespace(plan_trip=lambda request: TripPlan(**PLAN)))
    first = client.post("/api/trip/plan", json=REQUEST, headers={"X-Request-ID":"untrusted"})
    second = client.get("/health")
    assert first.json()["success"] is True and first.json()["data"]["city"] == "上海"
    assert first.headers["x-request-id"] not in ("untrusted", second.headers["x-request-id"])


def test_map_search_and_weather_routes_use_service(client, monkeypatch):
    service = SimpleNamespace(search_poi=lambda *args: [], get_weather=lambda city: [])
    monkeypatch.setattr(map_routes, "get_amap_service", lambda: service)
    monkeypatch.setattr(poi, "get_amap_service", lambda: service)
    for path in ("/api/map/poi?keywords=x&city=y", "/api/poi/search?keywords=x", "/api/map/weather?city=y"):
        response = client.get(path)
        assert response.status_code == 200 and response.json()["success"] is True


def test_unimplemented_route(client, monkeypatch):
    response = client.post("/api/map/route", json={"origin_address":"a","destination_address":"b","route_type":"invalid"})
    assert response.status_code == 422


@pytest.mark.parametrize("response", ["not json", "```json\n{}", "{}", "null"])
def test_invalid_plan_never_falls_back(response):
    planner = planner_module.MultiAgentTripPlanner.__new__(planner_module.MultiAgentTripPlanner)
    with pytest.raises(PlanParseError):
        planner._parse_response(response, TripRequest(**REQUEST))


def make_planner():
    planner = planner_module.MultiAgentTripPlanner.__new__(planner_module.MultiAgentTripPlanner)
    planner._run_lock = Lock()
    calls = []
    def invoke(messages, **kwargs):
        calls.append([dict(m) for m in messages])
        return json.dumps(PLAN)
    llm = SimpleNamespace(invoke=invoke)
    # Real SDK history behavior, no tools/network; verify our lifecycle isolation.
    for name in ("planner_agent",):
        setattr(planner, name, SimpleAgent(name=name, llm=llm, system_prompt="test"))
    return planner, calls


def test_history_isolated_between_requests_and_cleared_on_failure():
    planner, calls = make_planner()
    planner.plan_from_retrieval(TripRequest(**REQUEST), (), (), ())
    planner.plan_from_retrieval(TripRequest(**{**REQUEST, "city":"北京"}), (), (), ())
    assert len(calls) == 2 and all(len(messages) == 2 for messages in calls)
    assert all(agent._history == [] for agent in (planner.planner_agent,))
    planner.planner_agent.run = Mock(side_effect=RuntimeError("secret"))
    with pytest.raises(UpstreamError):
        planner.plan_from_retrieval(TripRequest(**REQUEST), (), (), ())
    assert planner.planner_agent._history == []
    assert planner._run_lock.acquire(blocking=False)
    planner._run_lock.release()


def test_overlapping_plan_is_rejected_and_lock_recovers():
    planner, calls = make_planner()
    started, release = Event(), Event()
    original = planner.planner_agent.run
    def blocked(query):
        started.set()
        assert release.wait(5)
        return original(query)
    planner.planner_agent.run = blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(planner.plan_from_retrieval, TripRequest(**REQUEST), (), (), ())
        try:
            assert started.wait(3)
            with pytest.raises(ServiceBusy):
                planner.plan_from_retrieval(TripRequest(**REQUEST), (), (), ())
        finally:
            release.set()
        assert pending.result(timeout=5).city == "上海"


def test_slow_planning_does_not_block_liveness(monkeypatch):
    started, release = Event(), Event()
    def blocked(request):
        started.set()
        assert release.wait(5)
        return TripPlan(**PLAN)
    monkeypatch.setattr(trip, "get_trip_planner_agent", lambda: SimpleNamespace(plan_trip=blocked))
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.create_app()), base_url="http://test") as client:
            pending = asyncio.create_task(client.post("/api/trip/plan", json=REQUEST))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                response = await asyncio.wait_for(client.get("/health"), timeout=2)
                assert response.status_code == 200
            finally:
                release.set()
            assert (await pending).status_code == 200
    asyncio.run(check())


def test_unsplash_failure_vs_empty(monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "image-secret")
    get_settings.cache_clear()
    service = unsplash_service.UnsplashService()
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.Timeout("secret")))
    with pytest.raises(UpstreamTimeout):
        service.search_photos("x")
    response = Mock()
    response.json.return_value = {"results": []}
    get = Mock(return_value=response)
    monkeypatch.setattr(requests, "get", get)
    assert service.search_photos("x") == []
    assert "client_id" not in get.call_args.kwargs["params"]
    assert get.call_args.kwargs["headers"]["Authorization"] == "Client-ID image-secret"


def test_llm_configuration_explicit_and_closed(monkeypatch):
    import hello_agents
    client = SimpleNamespace(_client=Mock())
    constructor = Mock(return_value=client)
    monkeypatch.setattr(hello_agents, "HelloAgentsLLM", constructor)
    monkeypatch.setattr(llm_service, "_llm_instance", None)
    assert llm_service.get_llm() is client
    assert constructor.call_args.kwargs == dict(api_key="test-secret", base_url="https://api.openai.com/v1", model="test-model", timeout=60, provider="custom")
    llm_service.reset_llm()
    llm_service.reset_llm()
    client._client.close.assert_called_once()


def test_cleanup_attempts_all_resources(monkeypatch):
    bad = Mock(side_effect=RuntimeError("secret"))
    good1, good2 = Mock(), Mock()
    monkeypatch.setattr(main, "reset_trip_planner", bad)
    monkeypatch.setattr(main, "reset_amap_service", good1)
    monkeypatch.setattr(main, "reset_llm", good2)
    with TestClient(main.create_app()):
        pass
    bad.assert_called_once()
    good1.assert_called_once()
    good2.assert_called_once()


def test_application_logs_do_not_include_exception_or_input(client, monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("trippilot")
    logger.addHandler(handler)
    monkeypatch.setattr(trip, "get_trip_planner_agent", Mock(side_effect=RuntimeError("test-secret private-user-input")))
    try:
        response = client.post("/api/trip/plan", json=REQUEST)
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert "test-secret" not in output and "private-user-input" not in output
    assert response.headers["x-request-id"] in output
    for line in output.splitlines():
        assert json.loads(line)["event"]


def test_sdk_wrapped_timeout_is_classified():
    planner, calls = make_planner()
    def fail(query):
        try:
            raise httpx.ReadTimeout("secret-url")
        except httpx.ReadTimeout:
            raise RuntimeError("SDK wrapper: secret-url")
    planner.planner_agent.run = fail
    with pytest.raises(UpstreamTimeout):
        planner.plan_from_retrieval(TripRequest(**REQUEST), (), (), ())
    assert planner.planner_agent._history == []


def test_poi_invalid_upstream_data_is_not_success(client, monkeypatch):
    from app.errors import ToolProtocolError
    class BadRuntime:
        async def call(self, name, arguments):
            raise ToolProtocolError()
    monkeypatch.setattr(poi, "get_amap_service", lambda: amap_service.AmapService(BadRuntime()))
    response = client.get("/api/poi/detail/test")
    assert response.status_code == 502
    assert response.json()["error_code"] == "TOOL_PROTOCOL_ERROR"


def test_missing_image_key_returns_configuration_error(client, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("must not request")))
    response = client.get("/api/poi/photo?name=x")
    assert response.status_code == 503
    assert response.json()["error_code"] == "CONFIGURATION_ERROR"
