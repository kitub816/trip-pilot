import json
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.api.main import create_app
from app.api.routes import trip
from app.errors import ConstraintExtractionError
from app.services.extraction_service import ConstraintExtractor, ExtractionRequest


class Agent:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.cleared = False
    def run(self, prompt):
        self.calls += 1
        assert json.loads(prompt)["user_text"]
        return self.response
    def clear_history(self):
        self.cleared = True


def test_valid_preview_one_call_and_no_history():
    agent = Agent('{"travelers":2,"budget_limit":2000,"currency":"CNY","must_visit":["故宫"]}')
    result = ConstraintExtractor(lambda: agent).extract("两人，总预算2000元，必须去故宫")
    assert result.travelers == 2 and result.budget_limit == 2000
    assert agent.calls == 1 and agent.cleared


@pytest.mark.parametrize("payload", [
    '{"travelers":99}', '{"budget_limit":-1,"currency":"CNY"}',
    '{"budget_limit":10,"currency":"USD"}', '{"budget_limit":10}',
    '{"must_visit":["故宫"],"avoid_places":["故宫"]}',
    '{"must_visit":[""]}', '{"surprise":true}', 'not json', 'x' * 16001,
])
def test_invalid_model_result_is_safe_failure(payload):
    agent = Agent(payload)
    with pytest.raises(ConstraintExtractionError):
        ConstraintExtractor(lambda: agent).extract("用户要求")
    assert agent.calls == 1 and agent.cleared


@pytest.mark.parametrize("text", [" ", "x" * 2001])
def test_input_is_bounded_before_model(text):
    with pytest.raises(ValidationError):
        ExtractionRequest(text=text)


def test_preview_route_does_not_start_planning(monkeypatch):
    monkeypatch.setattr(trip, "ConstraintExtractor", lambda: ConstraintExtractor(lambda: Agent('{"travelers":2}')))
    monkeypatch.setattr(trip, "get_trip_workflow", lambda: pytest.fail("preview must not plan"))
    with TestClient(create_app()) as client:
        response = client.post("/api/trip/extract", json={"text": "两人出游"})
        assert response.status_code == 200
        assert response.json()["travelers"] == 2


def test_whole_json_fence_is_accepted_without_scraping_prose():
    agent = Agent(chr(96) * 3 + 'json\n{"travelers":2}\n' + chr(96) * 3)
    assert ConstraintExtractor(lambda: agent).extract("两人").travelers == 2
