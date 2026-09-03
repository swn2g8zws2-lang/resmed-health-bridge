"""Environment-only configuration."""

from dataclasses import dataclass
from ipaddress import ip_address
import os


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/resmed.sqlite3"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000

    def __post_init__(self) -> None:
        if self.transport not in {"stdio", "streamable-http"}:
            raise ValueError("RESMED_MCP_TRANSPORT must be stdio or streamable-http")
        if self.transport == "stdio":
            return
        try:
            loopback = ip_address(self.host).is_loopback
        except ValueError:
            loopback = self.host == "localhost"
        if not loopback:
            raise ValueError("HTTP MCP is local-only; RESMED_MCP_HOST must be loopback")

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            db_path=os.getenv("RESMED_DB_PATH", "data/resmed.sqlite3"),
            transport=os.getenv("RESMED_MCP_TRANSPORT", "stdio"),
            host=os.getenv("RESMED_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("RESMED_MCP_PORT", "8000")),
        )
        return settings
