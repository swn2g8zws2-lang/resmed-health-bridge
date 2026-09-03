"""Integration tests against the real pinned MCP SDK, using synthetic records only."""

import json

import pytest

from resmed_health_bridge.config import Settings
from resmed_health_bridge.models import NightlyRecord
from resmed_health_bridge.server import create_server
from resmed_health_bridge.storage import NightlyStore

EXPECTED_TOOLS = {
    "get_last_night",
    "get_therapy_range",
    "get_ahi_trend",
    "get_leak_trend",
    "get_usage_trend",
    "get_pressure_summary",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mcp_server(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    store = NightlyStore(path)
    store.initialize()
    store.upsert(NightlyRecord(
        night="2026-01-03", usage_minutes=390, ahi=1.5,
        leak_95_lpm=7.2, pressure_95_cmh2o=9.8, source="synthetic",
    ))
    return create_server(Settings(db_path=str(path)))


@pytest.mark.anyio
async def test_exact_read_only_tool_inventory_and_schemas(mcp_server):
    tools = await mcp_server.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    assert not any(
        word in tool.name.lower()
        for tool in tools
        for word in ("set", "write", "update", "delete", "configure", "pressure_change")
    )
    assert all(tool.annotations.read_only_hint is True for tool in tools)
    assert all(tool.annotations.destructive_hint is False for tool in tools)
    assert all(tool.annotations.open_world_hint is False for tool in tools)

    by_name = {tool.name: tool for tool in tools}
    last_schema = by_name["get_last_night"].input_schema
    assert last_schema["type"] == "object"
    assert last_schema["properties"] == {}
    for name in EXPECTED_TOOLS - {"get_last_night"}:
        schema = by_name[name].input_schema
        assert set(schema["required"]) == {"start", "end"}
        assert schema["properties"]["start"]["format"] == "date"
        assert schema["properties"]["end"]["format"] == "date"


@pytest.mark.anyio
@pytest.mark.parametrize("name,arguments", [
    ("get_last_night", {}),
    ("get_therapy_range", {"start": "2026-01-03", "end": "2026-01-03"}),
    ("get_ahi_trend", {"start": "2026-01-03", "end": "2026-01-03"}),
    ("get_leak_trend", {"start": "2026-01-03", "end": "2026-01-03"}),
    ("get_usage_trend", {"start": "2026-01-03", "end": "2026-01-03"}),
    ("get_pressure_summary", {"start": "2026-01-03", "end": "2026-01-03"}),
])
async def test_each_tool_can_be_invoked_with_synthetic_data(mcp_server, name, arguments):
    result = await mcp_server.call_tool(name, arguments)
    assert not result.is_error
    content, structured = result.content, result.structured_content
    assert content
    payload = structured if structured is not None else json.loads(content[0].text)
    assert "2026-01-03" in json.dumps(payload)
