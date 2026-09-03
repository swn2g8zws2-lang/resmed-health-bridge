"""Environment-only configuration."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/resmed.sqlite3"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.getenv("RESMED_DB_PATH", "data/resmed.sqlite3"),
            transport=os.getenv("RESMED_MCP_TRANSPORT", "stdio"),
            host=os.getenv("RESMED_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("RESMED_MCP_PORT", "8000")),
        )
