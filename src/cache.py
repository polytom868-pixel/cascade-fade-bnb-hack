"""SQLite cache for CMC responses and trade data."""
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from src.config import DB_PATH

CACHE_TTL_SECONDS = 300  # 5 minutes


class Cache:
    """Async SQLite cache with WAL mode."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(DB_PATH)
        self._db: aiosqlite.Connection | None = None  # Instance variable, not class-level

    async def _connect(self) -> aiosqlite.Connection:
        if self._db is None or self._db.closed:
            self._db = await aiosqlite.connect(self._db_path, timeout=60.0)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
            await self._db.execute("PRAGMA temp_store=MEMORY")
            await self._db.execute("PRAGMA cache_size=10000")
            await self._init_schema()
        return self._db

    async def _init_schema(self) -> None:
        db = await self._connect()
        sql = """
        CREATE TABLE IF NOT EXISTS cmc_quotes (
            symbol TEXT PRIMARY KEY,
            data   TEXT NOT NULL,
            ts     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cmc_trending (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            data   TEXT NOT NULL,
            ts     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cmc_fear_greed (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            value  REAL,
            classification TEXT,
            ts     TEXT NOT NULL
        );
        """
        await db.executescript(sql)
        await db.commit()

    async def get_quote(self, symbol: str) -> dict[str, Any] | None:
        db = await self._connect()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS)).isoformat()
        async with db.execute(
            "SELECT data FROM cmc_quotes WHERE symbol=? AND ts>?", (symbol, cutoff)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return json.loads(row[0])
        return None

    async def set_quote(self, symbol: str, data: dict[str, Any]) -> None:
        db = await self._connect()
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO cmc_quotes(symbol, data, ts) VALUES(?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET data=excluded.data, ts=excluded.ts",
            (symbol, json.dumps(data), ts),
        )
        await db.commit()

    async def get_trending(self) -> list[dict[str, Any]] | None:
        db = await self._connect()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS)).isoformat()
        async with db.execute(
            "SELECT data FROM cmc_trending WHERE ts>? ORDER BY id DESC LIMIT 1", (cutoff,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return json.loads(row[0])
        return None

    async def set_trending(self, data: list[dict[str, Any]]) -> None:
        db = await self._connect()
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO cmc_trending(data, ts) VALUES(?,?)", (json.dumps(data), ts)
        )
        await db.commit()

    async def get_fear_greed(self) -> dict[str, Any] | None:
        db = await self._connect()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS)).isoformat()
        async with db.execute(
            "SELECT value, classification FROM cmc_fear_greed WHERE ts>? ORDER BY id DESC LIMIT 1",
            (cutoff,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {"value": row[0], "classification": row[1]}
        return None

    async def set_fear_greed(self, value: float, classification: str) -> None:
        db = await self._connect()
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO cmc_fear_greed(value, classification, ts) VALUES(?,?,?)",
            (value, classification, ts),
        )
        await db.commit()

    async def close(self) -> None:
        if self._db:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None