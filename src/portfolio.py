"""Portfolio tracking: holdings, cash, PnL, and value computation."""
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from src.config import DB_PATH, HEARTBEAT_SIZE_USD, MAX_POSITION_PCT
from src.utils import ensure_db, retry_async

STOP_LOSS_PCT = 0.05
TAKE_PROFIT_PCT = 0.10


def _compute_stop_take(entry_price: float) -> tuple[float, float]:
    """Compute stop-loss and take-profit prices from entry price."""
    stop = entry_price * (1 - STOP_LOSS_PCT)
    take = entry_price * (1 + TAKE_PROFIT_PCT)
    return round(stop, 6), round(take, 6)


def _sum_position_values(positions: list[dict], price_map: dict) -> float:
    """Sum the USD value of positions using quote prices from price_map."""
    total = 0.0
    for pos in positions:
        sym = pos["symbol"]
        quote = price_map.get(sym, {})
        price = quote.get("price", 0.0) or 0.0
        total += pos["amount"] * price
    return total

logger = logging.getLogger("cascadefade.portfolio")


class Portfolio:
    """Track open positions, cash, and portfolio value via SQLite."""

    def __init__(self, db_path: str = str(DB_PATH)) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        # Synchronous in-memory positions dict used by decision.py evaluate loop
        # {symbol: {"entry_ts": str, "entry_price": float, "units": float, "tx_hash": str|None}}
        self.positions: dict[str, dict[str, Any]] = {}

    async def _connect(self) -> aiosqlite.Connection:
        new_db = await ensure_db(self._db, self.db_path)
        if new_db is not self._db:
            self._db = new_db
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
            await self._db.execute("PRAGMA busy_timeout=30000")
            await self._ensure_schema()
        return new_db

    @staticmethod
    def _row_to_position(r: tuple) -> dict[str, Any]:
        return {
            "symbol": r[0],
            "entry_ts": r[1],
            "entry_price": r[2],
            "amount": r[3],
            "tx_hash": r[4],
            "stop_price": r[5],
            "take_price": r[6],
        }

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            side        TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            token_in    TEXT,
            token_out   TEXT,
            amount_in   REAL,
            amount_out  REAL,
            price_in    REAL,
            price_out   REAL,
            slippage_pct REAL,
            tx_hash     TEXT,
            signal_snapshot TEXT,
            realized_pnl REAL,
            portfolio_value REAL,
            mode        TEXT DEFAULT 'live',
            status      TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS positions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT NOT NULL UNIQUE,
            entry_ts    TEXT NOT NULL,
            entry_price REAL NOT NULL,
            amount      REAL NOT NULL,
            tx_hash     TEXT,
            stop_price  REAL,
            take_price  REAL,
            open        INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            total_value REAL NOT NULL,
            cash_value  REAL NOT NULL,
            positions_value REAL NOT NULL,
            peak_value  REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
        CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
        CREATE INDEX IF NOT EXISTS idx_portfolio_ts ON portfolio_snapshots(ts);
        """
        await db.executescript(sql)
        await db.commit()

    def total_exposure(self) -> float:
        """Total USD value of all open positions (using entry prices)."""
        return sum(
            p.get("units", 0.0) * p.get("entry_price", 0.0)
            for p in self.positions.values()
        )

    def get(self, symbol: str) -> dict[str, Any] | None:
        """Synchronously get a position's in-memory data."""
        return self.positions.get(symbol)

    def add(self, symbol: str, entry_price: float, units: float) -> None:
        """Synchronously add/update a position in-memory."""
        ts = datetime.now(timezone.utc).isoformat()
        self.positions[symbol] = {
            "entry_ts": ts,
            "entry_price": entry_price,
            "units": units,
            "tx_hash": None,
        }

    def remove(self, symbol: str) -> None:
        """Synchronously remove a position from in-memory cache."""
        self.positions.pop(symbol, None)

    def get_stop_price(self, symbol: str) -> float:
        """Return stop-loss price for a position, or 0 if not found."""
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        entry = pos.get("entry_price", 0.0)
        stop, _ = _compute_stop_take(entry)
        return stop

    def get_take_price(self, symbol: str) -> float:
        """Return take-profit price for a position, or 0 if not found."""
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        entry = pos.get("entry_price", 0.0)
        _, take = _compute_stop_take(entry)
        return take

    async def sync_position_to_db(self, symbol: str) -> None:
        """Persist an in-memory position to the DB (called async after swap)."""
        pos = self.positions.get(symbol)
        if not pos:
            return
        db = await self._connect()
        await db.execute("BEGIN IMMEDIATE")
        try:
            await self.add_position(
                symbol=symbol,
                entry_price=pos["entry_price"],
                amount=pos["units"],
                tx_hash=pos.get("tx_hash") or "",
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def remove_position_from_db(self, symbol: str) -> None:
        """Remove a position from DB (called async after sell swap)."""
        await self.close_position(symbol, exit_price=0.0, exit_tx_hash="")

    async def get_positions(self) -> list[dict[str, Any]]:
        """Return all open positions."""
        db = await self._connect()
        async with db.execute(
            "SELECT symbol, entry_ts, entry_price, amount, tx_hash, stop_price, take_price "
            "FROM positions WHERE open=1"
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_position(r) for r in rows]

    async def get_held_symbols(self) -> list[str]:
        """Return list of held symbol names."""
        positions = await self.get_positions()
        return [p["symbol"] for p in positions]

    async def add_position(
        self,
        symbol: str,
        entry_price: float,
        amount: float,
        tx_hash: str,
    ) -> None:
        """Record a new open position."""
        db = await self._connect()
        stop_price, take_price = _compute_stop_take(entry_price)
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT INTO positions(symbol, entry_ts, entry_price, amount, tx_hash, stop_price, take_price, open) "
                "VALUES(?,?,?,?,?,?,?,1) "
                "ON CONFLICT(symbol) DO UPDATE SET entry_ts=excluded.entry_ts, entry_price=excluded.entry_price, "
                "amount=excluded.amount, tx_hash=excluded.tx_hash, stop_price=excluded.stop_price, "
                "take_price=excluded.take_price, open=1",
                (symbol, ts, entry_price, amount, tx_hash, stop_price, take_price),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        logger.info("Position opened: %s @ %.4f x %.4f", symbol, entry_price, amount)

    async def close_position(self, symbol: str, exit_price: float, exit_tx_hash: str) -> dict[str, Any]:
        """Mark a position as closed and compute PnL."""
        db = await self._connect()
        async with db.execute(
            "SELECT entry_price, amount, tx_hash FROM positions WHERE symbol=? AND open=1", (symbol,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {"error": f"No open position for {symbol}"}

        entry_price, amount, entry_tx = row
        pnl = (exit_price - entry_price) * amount
        pnl_pct = (exit_price - entry_price) / entry_price if entry_price else 0

        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "UPDATE positions SET open=0 WHERE symbol=? AND open=1", (symbol,)
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        logger.info("Position closed: %s pnl=%.2f (%.2f%%)", symbol, pnl, pnl_pct * 100)
        return {
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "amount": amount,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "entry_tx": entry_tx,
            "exit_tx": exit_tx_hash,
        }

    async def update_cash(self, amount_usd: float) -> None:
        """Persist the current cash balance to the latest snapshot.

        Called after every swap so compute_value() always reads fresh cash.
        """
        db = await self._connect()
        # Patch the most recent snapshot's cash_value, or insert a new one
        async with db.execute(
            "SELECT id, total_value, positions_value, peak_value FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute("BEGIN IMMEDIATE")
        try:
            if row:
                total = amount_usd + (row[2] or 0.0)
                peak = max(row[3] or total, total)
                await db.execute(
                    "UPDATE portfolio_snapshots SET cash_value=?, total_value=?, peak_value=? WHERE id=?",
                    (amount_usd, total, peak, row[0]),
                )
            else:
                await db.execute(
                    "INSERT INTO portfolio_snapshots(ts, total_value, cash_value, positions_value, peak_value) "
                    "VALUES(?,?,?,?,?)",
                    (ts, amount_usd, amount_usd, 0.0, amount_usd),
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        logger.debug("Cash updated to %.2f", amount_usd)

    async def compute_value(
        self,
        price_map: dict[str, dict[str, Any]],
        cash_usd: float,
    ) -> dict[str, Any]:
        """Compute total portfolio value from positions + cash.

        price_map: {symbol: {price: float, ...}}
        Returns dict with total, cash, positions_value, peak, drawdown info.
        """
        positions = await self.get_positions()
        positions_value = _sum_position_values(positions, price_map)

        total = cash_usd + positions_value

        # Update peak and compute drawdown
        db = await self._connect()
        async with db.execute(
            "SELECT MAX(total_value) FROM portfolio_snapshots"
        ) as cur:
            row = await cur.fetchone()
        peak = row[0] if row and row[0] is not None else total
        peak = max(peak, total)

        drawdown_pct = (peak - total) / peak if peak > 0 else 0.0

        # Record snapshot
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT INTO portfolio_snapshots(ts, total_value, cash_value, positions_value, peak_value) "
                "VALUES(?,?,?,?,?)",
                (ts, total, cash_usd, positions_value, peak),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return {
            "total": total,
            "cash": cash_usd,
            "positions_value": positions_value,
            "peak": peak,
            "drawdown_pct": drawdown_pct,
        }

    async def get_cash_balance(self) -> float:
        """Return current cash balance from most recent snapshot."""
        db = await self._connect()
        async with db.execute(
            "SELECT cash_value FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0.0

    async def initialize_cash(self, amount_usd: float) -> None:
        """Set starting cash balance."""
        db = await self._connect()
        ts = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO portfolio_snapshots(ts, total_value, cash_value, positions_value, peak_value) "
            "VALUES(?,?,?,?,?)",
            (ts, amount_usd, amount_usd, 0.0, amount_usd),
        )
        await db.commit()
        logger.info("Portfolio initialized with cash=%.2f", amount_usd)

    async def get_last_trade_ts(self) -> str | None:
        """ISO timestamp of last recorded trade."""
        db = await self._connect()
        async with db.execute(
            "SELECT ts FROM trades ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def close(self) -> None:
        if self._db:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None