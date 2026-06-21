"""Shared DB constants and helpers for CascadeFade."""
import aiosqlite

WAL_AUTOCHECKPOINT = 1000
CACHE_SIZE_PAGES = 10000
BUSY_TIMEOUT_MS = 30000
TEMP_STORE = "MEMORY"


async def apply_pragmas(conn: aiosqlite.Connection) -> None:
    """Apply recommended SQLite pragmas for CascadeFade."""
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=30000")
    await conn.execute("PRAGMA temp_store=MEMORY")
    await conn.execute("PRAGMA cache_size=10000")
    await conn.execute("PRAGMA wal_autocheckpoint=1000")