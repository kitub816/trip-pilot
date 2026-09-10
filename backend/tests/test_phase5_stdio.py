"""Exercise real local MCP transport and verify the owned subprocess exits."""
import asyncio
import sys
from pathlib import Path

import pytest
import mcp.client.stdio as stdio
from app.errors import UpstreamTimeout
from app.services import tool_runtime as module


@pytest.mark.parametrize("city", ["normal", "slow"])
def test_real_mcp_stdio_process_is_closed(monkeypatch, city):
    processes = []
    original_create = stdio._create_platform_compatible_process
    original_parameters = module.StdioServerParameters

    async def create(**kwargs):
        process = await original_create(**kwargs)
        processes.append(process)
        return process

    fixture = str(Path(__file__).parent / "fixtures" / "mcp_server.py")
    monkeypatch.setattr(stdio, "_create_platform_compatible_process", create)
    monkeypatch.setattr(module, "StdioServerParameters", lambda **kwargs: original_parameters(
        command=sys.executable, args=[fixture]))
    runtime = module.ToolRuntime(timeout=3, total_timeout=10, max_attempts=1)
    if city == "slow":
        with pytest.raises(UpstreamTimeout):
            asyncio.run(runtime.call("maps_weather", {"city": city}))
    else:
        result = asyncio.run(runtime.call("maps_weather", {"city": city}))
        assert result.payload == {"forecasts": []}
    assert len(processes) == 1
    assert processes[0].returncode is not None
