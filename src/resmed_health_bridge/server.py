"""Read-only MCP server exposing cached therapy summaries."""

from __future__ import annotations

from datetime import date

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .service import TherapyQueries
from .storage import NightlyStore


def create_server(settings: Settings | None = None) -> FastMCP:
    settings = settings or Settings.from_env()
    store = NightlyStore(settings.db_path)
    store.initialize()
    queries = TherapyQueries(store)
    mcp = FastMCP("ResMed Health Bridge", host=settings.host, port=settings.port)

    @mcp.tool()
    def get_last_night() -> dict | None:
        """Return the newest locally cached nightly therapy summary."""
        return queries.last_night()

    @mcp.tool()
    def get_therapy_range(start: date, end: date) -> list[dict]:
        """Return cached nightly summaries for an inclusive ISO-date range."""
        return queries.therapy_range(start, end)

    @mcp.tool()
    def get_ahi_trend(start: date, end: date) -> dict:
        """Return nightly AHI points and their average for an inclusive range."""
        return queries.metric_trend("ahi", start, end)

    @mcp.tool()
    def get_leak_trend(start: date, end: date) -> dict:
        """Return nightly 95th-percentile leak points (L/min) and average."""
        return queries.metric_trend("leak_95_lpm", start, end)

    @mcp.tool()
    def get_usage_trend(start: date, end: date) -> dict:
        """Return nightly usage-minute points and average for a range."""
        return queries.metric_trend("usage_minutes", start, end)

    @mcp.tool()
    def get_pressure_summary(start: date, end: date) -> dict:
        """Summarize cached 95th-percentile pressure (cmH2O) for a range."""
        return queries.pressure_summary(start, end)

    return mcp


def main() -> None:
    settings = Settings.from_env()
    if settings.transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("RESMED_MCP_TRANSPORT must be stdio, sse, or streamable-http")
    create_server(settings).run(transport=settings.transport)


if __name__ == "__main__":
    main()
