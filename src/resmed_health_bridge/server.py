"""Read-only MCP server exposing cached therapy summaries."""

from __future__ import annotations

from datetime import date

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .config import Settings
from .service import TherapyQueries
from .storage import NightlyStore


def create_server(settings: Settings | None = None) -> MCPServer:
    settings = settings or Settings.from_env()
    store = NightlyStore(settings.db_path)
    store.initialize()
    queries = TherapyQueries(store)
    mcp = MCPServer("resmed-health-bridge", title="ResMed Health Bridge")
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @mcp.tool(annotations=read_only)
    def get_last_night() -> dict | None:
        """Return the newest locally cached nightly therapy summary."""
        return queries.last_night()

    @mcp.tool(annotations=read_only)
    def get_therapy_range(start: date, end: date) -> list[dict]:
        """Return cached nightly summaries for an inclusive ISO-date range."""
        return queries.therapy_range(start, end)

    @mcp.tool(annotations=read_only)
    def get_ahi_trend(start: date, end: date) -> dict:
        """Return nightly AHI points and their average for an inclusive range."""
        return queries.metric_trend("ahi", start, end)

    @mcp.tool(annotations=read_only)
    def get_leak_trend(start: date, end: date) -> dict:
        """Return nightly 95th-percentile leak points (L/min) and average."""
        return queries.metric_trend("leak_95_lpm", start, end)

    @mcp.tool(annotations=read_only)
    def get_usage_trend(start: date, end: date) -> dict:
        """Return nightly usage-minute points and average for a range."""
        return queries.metric_trend("usage_minutes", start, end)

    @mcp.tool(annotations=read_only)
    def get_pressure_summary(start: date, end: date) -> dict:
        """Summarize cached 95th-percentile pressure (cmH2O) for a range."""
        return queries.pressure_summary(start, end)

    return mcp


def main() -> None:
    settings = Settings.from_env()
    if settings.transport not in {"stdio", "streamable-http"}:
        raise ValueError("RESMED_MCP_TRANSPORT must be stdio or streamable-http")
    server = create_server(settings)
    if settings.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="streamable-http", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
