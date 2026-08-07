"""Configuration, read from the environment. No credentials in source."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Hard cap on rows returned by any tool, enforced in Python rather than left
# to the model or the prompt. A tool that would exceed this truncates and says
# so in its envelope.
MAX_ROWS = 5000


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env reader. Avoids a dependency for six variables."""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class Settings:
    def __init__(self) -> None:
        load_dotenv()
        self.readonly_url = os.environ.get("NEON_READONLY_URL", "")
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.statement_timeout_ms = int(os.environ.get("STATEMENT_TIMEOUT_MS", "8000"))
        self.max_tool_calls_per_turn = int(os.environ.get("MAX_TOOL_CALLS_PER_TURN", "10"))
        # Configurable so the cost/quality tradeoff can be re-tested without a
        # code change. Opus 5 for correctness on a rule-dense prompt; Sonnet 5
        # is the cheaper fallback if spend becomes the constraint.
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
        self.effort = os.environ.get("ANTHROPIC_EFFORT", "high")
        self.pool_min_size = int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
        self.pool_max_size = int(os.environ.get("DB_POOL_MAX_SIZE", "5"))
        # Everything the app WRITES is relocatable, because in the container it
        # runs as a non-root user against a read-only code tree. Each of these
        # defaults to where it has always lived locally; the compose file points
        # them all at the one mounted volume.
        #
        # Saved analyses and the cache survive an image rebuild by living on
        # that volume. The run_sql log has to be writable for a different
        # reason: it is the audit trail of every raw SQL statement the model
        # executed, and a deployment where it silently fails to write is a
        # deployment with no record of what was run.
        self.analyses_db_path = Path(
            os.environ.get(
                "ANALYSES_DB_PATH", str(REPO_ROOT / "backend" / "data" / "analyses.sqlite")
            )
        )
        self.cache_db_path = Path(
            os.environ.get(
                "CACHE_DB_PATH", str(REPO_ROOT / "backend" / "cache" / "tool_cache.sqlite")
            )
        )
        self.run_sql_log_path = Path(
            os.environ.get(
                "RUN_SQL_LOG_PATH", str(REPO_ROOT / "backend" / "logs" / "run_sql.jsonl")
            )
        )

    def require_db(self) -> str:
        if not self.readonly_url:
            raise RuntimeError(
                "NEON_READONLY_URL is not set. The application connects only as the "
                "dedicated read-only role; see the README for the CREATE ROLE SQL."
            )
        return self.readonly_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
