import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from app.errors import (NoCandidates, ServiceBusy, ToolArgumentError, ToolProtocolError,
                        UpstreamError, UpstreamTimeout)
from app.services.tool_runtime import ToolRuntime, decode_result, parse_payload


class FakeSession:
    def __init__(self, payload='{"forecasts":[]}', delay=0, schema=None):
        self.payload, self.delay = payload, delay
        self.schema = schema or {"type": "object", "required": ["city"], "properties": {"city": {"type": "string"}}}
        self.calls = 0

    async def initialize(self):
        pass

    async def list_tools(self):
        return ListToolsResult(tools=[Tool(name="maps_weather", inputSchema=self.schema)])

    async def call_tool(self, name, arguments):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return CallToolResult(content=[TextContent(type="text", text=self.payload)])


def factory_for(session, events):
    @asynccontextmanager
    async def factory():
        events.append("open")
        try:
            yield session
        finally:
            events.append("close")
    return factory


def test_success_provenance_and_close():
    events = []
    session = FakeSession()
    result = asyncio.run(ToolRuntime(factory_for(session, events)).call("maps_weather", {"city": " 上海 "}))
    assert result.payload == {"forecasts": []}
    assert result.provenance.attempts == 1
    assert result.provenance.elapsed_ms >= 0
    assert result.provenance.retrieved_at.tzinfo is not None
    assert events == ["open", "close"]


@pytest.mark.parametrize("name,args", [("unknown", {}), ("maps_weather", {}),
    ("maps_weather", {"city": ""}), ("maps_weather", {"city": "上海", "secret": "x"})])
def test_validation_precedes_process_start(name, args):
    events = []
    runtime = ToolRuntime(factory_for(FakeSession(), events))
    with pytest.raises(ToolArgumentError):
        asyncio.run(runtime.call(name, args))
    assert events == []


def test_server_schema_mismatch_does_not_call_or_retry():
    session = FakeSession(schema={"type": "object", "required": ["different"]})
    events = []
    with pytest.raises(ToolProtocolError):
        asyncio.run(ToolRuntime(factory_for(session, events)).call("maps_weather", {"city": "上海"}))
    assert session.calls == 0 and events == ["open", "close"]


def test_timeout_retries_are_bounded_and_every_session_closes():
    events = []
    runtime = ToolRuntime(factory_for(FakeSession(delay=10), events), timeout=0.02,
                          total_timeout=1, max_attempts=2, backoff=0)
    with pytest.raises(UpstreamTimeout):
        asyncio.run(runtime.call("maps_weather", {"city": "上海"}))
    assert events == ["open", "close", "open", "close"]


def test_total_deadline_includes_backoff():
    events = []
    runtime = ToolRuntime(factory_for(FakeSession(delay=10), events), timeout=0.01,
                          total_timeout=0.03, max_attempts=3, backoff=2)
    with pytest.raises(UpstreamTimeout):
        asyncio.run(runtime.call("maps_weather", {"city": "上海"}))
    assert events == ["open", "close"]


def test_explicit_rate_limit_retries_but_protocol_error_does_not():
    async def run(payload, expected):
        events = []
        session = FakeSession(payload=payload)
        runtime = ToolRuntime(factory_for(session, events), max_attempts=2, backoff=0)
        with pytest.raises(UpstreamError):
            await runtime.call("maps_weather", {"city": "上海"})
        assert session.calls == expected
    asyncio.run(run('{"status":"0","infocode":"10003"}', 2))
    asyncio.run(run('secret invalid response', 1))
    asyncio.run(run('{"error":"private error"}', 1))


def test_cancellation_closes_session_releases_quota_and_never_retries():
    async def run():
        events = []
        session = FakeSession(delay=10)
        runtime = ToolRuntime(factory_for(session, events), concurrency=1)
        task = asyncio.create_task(runtime.call("maps_weather", {"city": "上海"}))
        while not events:
            await asyncio.sleep(0)
        with pytest.raises(ServiceBusy):
            await runtime.call("maps_weather", {"city": "北京"})
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == ["open", "close"]
        session.delay = 0
        await runtime.call("maps_weather", {"city": "北京"})
        runtime.close()
        with pytest.raises(ServiceBusy):
            await runtime.call("maps_weather", {"city": "北京"})
    asyncio.run(run())


def test_two_isolated_sessions_overlap_without_sharing():
    async def run():
        active, maximum = 0, 0
        both_entered = asyncio.Event()
        @asynccontextmanager
        async def factory():
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            if active == 2:
                both_entered.set()
            try:
                await asyncio.wait_for(both_entered.wait(), 1)
                yield FakeSession()
            finally:
                active -= 1
        runtime = ToolRuntime(factory, concurrency=2)
        await asyncio.gather(runtime.call("maps_weather", {"city": "上海"}),
                             runtime.call("maps_weather", {"city": "北京"}))
        assert maximum == 2 and active == 0
    asyncio.run(run())


@pytest.mark.parametrize("payload", ['null', '42', '{} prose', 'failed {"pois":[]}', '{"status":"0"}', '{"error":"x"}'])
def test_bad_payloads_are_not_empty_success(payload):
    with pytest.raises(UpstreamError):
        parse_payload(payload)


def test_json_fence_and_mcp_structured_content():
    assert parse_payload('```json\n{"pois":[]}\n```') == {"pois": []}
    assert decode_result(CallToolResult(content=[], structuredContent={"pois": []})) == {"pois": []}
    with pytest.raises(UpstreamError):
        decode_result(CallToolResult(isError=True, content=[TextContent(type="text", text='{"pois":[]}')]))
