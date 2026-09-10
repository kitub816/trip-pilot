"""Offline MCP stdio fixture; never contacts an external service."""
import asyncio
from mcp.server.fastmcp import FastMCP

server = FastMCP("trippilot-offline-fixture")


@server.tool()
async def maps_weather(city: str) -> dict:
    if city == "slow":
        await asyncio.sleep(60)
    return {"forecasts": []}


if __name__ == "__main__":
    server.run(transport="stdio")
