"""Trade logging and journal via SQLite."""
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from src.config import DB_PATH
from src.utils import ensure_db

logger = logging.getLogger("cascadefade.log")


class TradeLogger:
    """Structured trade journal using SQLite."""

    def __init__(self, db_path: str = str(DB_PATH)) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def _connect(self) -> aiosqlite.Connection:
        new_db = await ensure_db(self._db, self.db_path)
        if new_db is not self._db:
            self._db = new_db
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            # Retry writes for up to 30s on lock contention — prevents SQLITE_BUSY failures
            await self._db.execute("PRAGMA busy_timeout=30000")
            # Truncate WAL to keep wal file bounded
            await self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return new_db

    async def log_trade(
        self,
        side: str,
        symbol: str,
        token_in: str,
        token_out: str,
        amount_in: float,
        amount_out: float,
        price_in: float,
        price_out: float,
        slippage_pct: float,
        tx_hash: str | None,
        signal_snapshot: dict[str, Any],
        realized_pnl: float | None,
        portfolio_value: float,
        mode: str = "live",
        status: str = "pending",
    ) -> int | None:
        """Record a trade in the journal. Returns row id."""
        db = await self._connect()
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "INSERT INTO trades(ts, side, symbol, token_in, token_out, amount_in, amount_out, "
                "price_in, price_out, slippage_pct, tx_hash, signal_snapshot, realized_pnl, "
                "portfolio_value, mode, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ts,
                    side,
                    symbol,
                    token_in,
                    token_out,
                    amount_in,
                    amount_out,
                    price_in,
                    price_out,
                    slippage_pct,
                    tx_hash,
                    json.dumps(signal_snapshot),
                    realized_pnl,
                    portfolio_value,
                    mode,
                    status,
                ),
            )
            row_id = cursor.lastrowid
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        logger.info(
            "Trade logged #%d: %s %s @ %.4f (mode=%s status=%s)",
            row_id,
            side,
            symbol,
            amount_in,
            mode,
            status,
        )
        return row_id

    async def update_trade_status(self, row_id: int, status: str) -> None:
        db = await self._connect()
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute("UPDATE trades SET status=? WHERE id=?", (status, row_id))
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def log_decision(
        self,
        signal: str,
        symbol: str,
        action: str,
        reason: str,
        confidence: float,
        cmc_data: dict[str, Any],
    ) -> int | None:
        """Log a decision even when no trade is executed."""
        db = await self._connect()
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "INSERT INTO trades(ts, side, symbol, signal_snapshot, mode, status) VALUES(?,?,?,?,?,?)",
                (ts, "decision", symbol, json.dumps({"signal": signal, "action": action, "reason": reason, "confidence": confidence, "cmc": cmc_data}), "paper", "logged"),
            )
            row_id = cursor.lastrowid
            await db.commit()
            return row_id
        except Exception:
            await db.rollback()
            raise

    async def get_recent_trades(self, limit: int = 20) -> list[dict[str, Any]]:
        db = await self._connect()
        async with db.execute(
            "SELECT id, ts, side, symbol, amount_in, amount_out, price_in, price_out, "
            "slippage_pct, tx_hash, realized_pnl, portfolio_value, mode, status "
            "FROM trades ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        keys = ["id", "ts", "side", "symbol", "amount_in", "amount_out", "price_in", "price_out",
                "slippage_pct", "tx_hash", "realized_pnl", "portfolio_value", "mode", "status"]
        return [dict(zip(keys, row)) for row in rows]

    async def close(self) -> None:
        if self._db:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None


# Module-level quick log for synchronous code
def log_trade(side: str, symbol: str, units: float, price: float, value: float, tx_hash: str | None = None, slippage: float = 0.0) -> None:
    """Log a trade synchronously (decision.py uses this)."""
    logger.info("TRADE | %s | %s | units=%.6f | price=%.4f | value=%.2f | tx=%s | slippage=%.2f%%",
                side, symbol, units, price, value, tx_hash or "", slippage)
