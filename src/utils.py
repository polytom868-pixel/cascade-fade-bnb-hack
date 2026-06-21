"""Shared helpers for CascadeFade."""
import asyncio
import logging
import re
from typing import Any, Awaitable, Callable

import aiosqlite

from eth_utils import to_checksum_address

logger = logging.getLogger("cascadefade")


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def to_checksum(addr: str) -> str:
    """Return checksummed address if valid, else original."""
    try:
        return to_checksum_address(addr)
    except Exception:
        return addr


def fmt_usd(value: float) -> str:
    """Format a USD amount with 2 decimals."""
    return f"${value:,.2f}"


def fmt_pct(value: float) -> str:
    """Format a percentage with 2 decimals."""
    return f"{value * 100:.2f}%"


def fmt_bnb(value: float) -> str:
    """Format a BNB amount with 4 decimals."""
    return f"{value:,.4f} BNB"


def parse_twak_json_output(stdout: str) -> dict[str, Any]:
    """Parse JSON output from `twak ... --json`.

    TWAK may print non-JSON lines before/after the JSON payload.
    We scan for the first `{` and last `}` to extract the JSON block.
    """
    import json

    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in stdout: {stdout[:200]}")
    return json.loads(stdout[start : end + 1])


def parse_tx_hash_from_stdout(stdout: str) -> str | None:
    """Attempt to extract a BSC tx hash from TWAK stdout."""
    match = re.search(r"0x[a-fA-F0-9]{64}", stdout)
    return match.group(0) if match else None


async def retry_async(
    coro_factory: Callable[[], Awaitable[Any]],
    retries: int = 3,
    backoff: float = 1.5,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Any:
    """Retry an async coroutine with exponential backoff."""
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return await coro_factory()
        except exceptions as exc:
            last_exc = exc
            if attempt < retries:
                wait = backoff * (2 ** attempt)
                logger.warning("Retry %d/%d after %.1fs: %s", attempt + 1, retries, wait, exc)
                await asyncio.sleep(wait)
    raise last_exc


async def ensure_db(db: aiosqlite.Connection | None, db_path: str) -> aiosqlite.Connection:
    """Return a live aiosqlite connection, reconnecting if necessary."""
    if db is not None:
        try:
            # Lightweight: sqlite3_closed check equivalent
            if hasattr(db, '_connection') and db._connection is not None:
                return db
        except Exception:
            pass
    new_db: aiosqlite.Connection = await aiosqlite.connect(db_path, timeout=60.0)
    return new_db


async def apply_db_pragmas(db: aiosqlite.Connection) -> None:
    """Apply standard performance pragmas."""
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=30000")
    await db.execute("PRAGMA temp_store=MEMORY")
    await db.execute("PRAGMA cache_size=10000")
    await db.execute("PRAGMA wal_autocheckpoint=1000")
