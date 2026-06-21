#!/usr/bin/env python3
"""CascadeFade — Main asyncio trading agent loop."""
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

# Ensure src/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.cache import Cache
from src.cmc_client import CMCClient
from src.config import (
    AGENT_MODE,
    LOG_LEVEL,
    TRADE_INTERVAL_MINUTES,
    ALLOWLIST,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    NARRATIVE_BASKETS,
)
from src.config import CASH_CURRENCY, RISK_CURRENCY
from src.decision import DecisionEngine
from src.log import TradeLogger
from src.portfolio import Portfolio
from src.quoter import Quoter
from src.risk import RiskGuard
from src.signal import SignalEngineClass
from src.twak import TWAKExecutor
from src.utils import setup_logging

logger = logging.getLogger("cascadefade.agent")

# ── globals for graceful shutdown ─────────────────────────────────────────
_shutdown_requested = asyncio.Event()


def _signal_handler(sig: int, frame: Any) -> None:
    logger.warning("SIGINT received — requesting graceful shutdown...")
    _shutdown_requested.set()


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


class Agent:
    """Asyncio trading agent that loops forever until shutdown."""

    def __init__(self, mode: str | None = None, initial_cash: float = 1000.0, interval_minutes: int = TRADE_INTERVAL_MINUTES) -> None:
        self.mode = (mode or os.getenv("AGENT_MODE", "paper")).lower()
        self.initial_cash = initial_cash
        self.interval = timedelta(minutes=interval_minutes)

        # Core components
        self.cache = Cache()
        self.cmc = CMCClient()
        self.portfolio = Portfolio()
        self.quoter = Quoter() if self.mode != "paper" else None
        self.twak = TWAKExecutor()
        self.signal_engine = SignalEngineClass(self.cmc)
        self.risk_manager = RiskGuard(self.portfolio)
        self.trade_logger = TradeLogger()

        self.decision = DecisionEngine(
            twak_client=self.twak,
            portfolio=self.portfolio,
            risk=self.risk_manager,
            signal_engine=self.signal_engine,
        )

        self._start_ts = datetime.now(timezone.utc)
        self._cycle_count = 0

    async def setup(self) -> None:
        """Initialize portfolio and verify CMC / TWAK connectivity."""
        setup_logging(os.getenv("LOG_LEVEL", "INFO"))
        logger.info("=" * 60)
        logger.info("CascadeFade Agent  |  Mode: %s  |  Start: %s", self.mode, self._start_ts.isoformat())
        logger.info("=" * 60)

        # Verify CMC
        try:
            test_quotes = await self.cmc.get_bulk_quotes({"BNB": ""})
            if test_quotes.get("BNB", {}).get("price", 0) > 0:
                logger.info("CMC connection OK — BNB price=%.2f", test_quotes["BNB"]["price"])
            else:
                logger.warning("CMC returned empty BNB quote — check API key")
        except Exception as exc:
            logger.error("CMC connectivity check failed: %s", exc)
            raise RuntimeError("Cannot start without CMC data") from exc

        # Verify BSC RPC (skip in paper mode)
        if self.mode == "paper":
            logger.warning("Paper mode — skipping BSC RPC check")
        elif self.quoter is None:
            # Lazy-load quoter for non-paper mode
            self.quoter = Quoter()
            if not self.quoter.w3.is_connected():
                logger.error("BSC RPC not connected — check BNB_RPC_URL")
                raise RuntimeError("Cannot start without BSC RPC")
            logger.info("BSC RPC connected — block=%s", self.quoter.w3.eth.block_number)
        elif not self.quoter.w3.is_connected():
            logger.error("BSC RPC not connected — check BNB_RPC_URL")
            raise RuntimeError("Cannot start without BSC RPC")
        else:
            logger.info("BSC RPC connected — block=%s", self.quoter.w3.eth.block_number)

        # Initialize portfolio cash
        await self.portfolio.initialize_cash(self.initial_cash)
        logger.info("Portfolio initialized: cash=$%.2f", self.initial_cash)

        # WAL checkpoint to reduce DB file size on startup
        db = await self.portfolio._connect()
        await db.commit()  # ensure initialize_cash writes are flushed
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await db.commit()

        # Print wallet address if TWAK available
        try:
            addr = await self.twak.get_address()
            if addr:
                logger.info("TWAK wallet address: %s", addr)
            else:
                logger.warning("TWAK wallet address not returned")
        except Exception as exc:
            logger.warning("TWAK wallet check failed: %s", exc)

    async def health_check(self) -> None:
        """Print periodic status line."""
        now = datetime.now(timezone.utc)
        elapsed = now - self._start_ts
        held = await self.portfolio.get_held_symbols()
        last_trade = await self.portfolio.get_last_trade_ts()
        heartbeat = await self.risk_manager.check_heartbeat()
        logger.info(
            "HEALTH | cycles=%d elapsed=%s held=%s last_trade=%s next_heartbeat=%s",
            self._cycle_count,
            str(elapsed).split(".")[0],
            held,
            last_trade or "none",
            "YES" if heartbeat["needed"] else "no",
        )

    async def run_cycle(self) -> dict[str, Any]:
        """Execute one trading cycle."""
        self._cycle_count += 1
        start = datetime.now(timezone.utc)

        # ── Phase 1: parallel data fetch — 3 sequential awaits → 1 gather ──────────
        #MICRO-OPT: run all independent portfolio queries in a single gather to cut
        #epoll wakeups from 3 → 1 and eliminate 2 separate SQLite poll cycles.
        held_symbols, positions, cash = await asyncio.gather(
            self.portfolio.get_held_symbols(),
            self.portfolio.get_positions(),
            self.portfolio.get_cash_balance(),
        )

        # Rate-limit cycle start log: print once per 5th cycle (same cadence as health)
        if self._cycle_count % 5 == 0:
            logger.info("--- Cycle %d | %s ---", self._cycle_count, start.isoformat())

        # ── Phase 2: build symbol set from cached data (no extra DB round-trip) ─────
        symbols_needed: set[str] = set(held_symbols)
        for tokens in NARRATIVE_BASKETS.values():
            symbols_needed.update(tokens)
        symbols_needed.add(RISK_CURRENCY)
        symbols_needed.add("BNB")  # need BNB price for cash valuation

        # ── Phase 3: fetch prices once per cycle (MICRO-OPT: no duplicate calls) ───
        price_map: dict[str, float] = {}
        if symbols_needed:
            try:
                quotes = await self.cmc.get_bulk_quotes({s: "" for s in symbols_needed})
                price_map = {s: q.get("price", 0.0) for s, q in quotes.items()}
            except Exception as exc:
                logger.warning("CMC bulk quotes failed: %s", exc)

        # ── Phase 4: stop/take-profit check — uses positions from Phase 1 gather ────
        #MICRO-OPT: no extra get_positions() call; reuse `positions` fetched above.
        forced_sells = []
        for pos in positions:
            sym = pos["symbol"]
            stop_price = pos.get("stop_price") or 0.0
            take_price = pos.get("take_price") or 0.0
            current_price = price_map.get(sym, 0.0)
            if current_price <= 0:
                continue
            if stop_price > 0 and current_price <= stop_price:
                logger.info("STOP-LOSS triggered: %s price=%.4f <= stop=%.4f", sym, current_price, stop_price)
                forced_sells.append({"token": sym, "reason": "stop_loss", "price": current_price})
            elif take_price > 0 and current_price >= take_price:
                logger.info("TAKE-PROFIT triggered: %s price=%.4f >= take=%.4f", sym, current_price, take_price)
                forced_sells.append({"token": sym, "reason": "take_profit", "price": current_price})

        # ── Phase 5: run decision engine (cash from Phase 1 gather, price_map reused) ─
        try:
            summary = await self.decision.run_cycle(cash, price_map)
        except Exception as exc:
            logger.exception("Cycle %d failed: %s", self._cycle_count, exc)
            summary = {"error": str(exc), "actions": {"buys": [], "sells": [], "holds": [], "rejections": []}, "notes": []}

        # ── Phase 6: execute forced sells in parallel ──────────────────────────────
        if forced_sells:
            sell_tasks = [self._execute_sell(sell, price_map) for sell in forced_sells]
            results = await asyncio.gather(*sell_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("Gather exception: %s", r)

        # Prepend forced sells to the decision's sell actions
        if forced_sells:
            summary.setdefault("actions", {})
            summary["actions"].setdefault("sells", [])
            summary["actions"]["sells"] = forced_sells + summary["actions"]["sells"]

        # ── Phase 7: health summary log (every 5th cycle, reuse held_symbols) ───────
        #MICRO-OPT: held_symbols already fetched in Phase 1 — no duplicate get_held_symbols() call.
        #MICRO-OPT: fetch last_trade only when actually logging, not on every cycle.
        if self._cycle_count % 5 == 0:
            last_trade = await self.portfolio.get_last_trade_ts()
            logger.info(
                "agent_cycle_summary | cycles=%d elapsed=%s held=%s last_trade=%s",
                self._cycle_count,
                str((datetime.now(timezone.utc) - self._start_ts)).split(".")[0],
                held_symbols,
                last_trade or "none",
            )

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info("Cycle %d complete in %.1fs | actions=%s", self._cycle_count, elapsed, summary.get("actions", []))
        return summary

    async def main_loop(self) -> None:
        """Run trading loop until shutdown signal."""
        await self.setup()

        while not _shutdown_requested.is_set():
            # MICRO-OPT: asyncio.timeout() (3.11+) avoids wait_for stack frame overhead
            try:
                async with asyncio.timeout(self.interval.total_seconds()):
                    await _shutdown_requested.wait()
            except asyncio.TimeoutError:
                pass  # interval elapsed normally

            if _shutdown_requested.is_set():
                break

            # MICRO-OPT: health_check omitted here — run_cycle() logs health every 5th
            # cycle internally, eliminating a redundant get_held_symbols() +
            # get_last_trade_ts() + check_heartbeat() round-trip per cycle.
            await self.run_cycle()

        await self.shutdown()

    async def _execute_sell(self, sell: dict[str, Any], price_map: dict[str, float]) -> None:
        """Execute a single forced sell (stop-loss or take-profit)."""
        sym = sell["token"]
        price = sell["price"]
        # Read from DB to avoid stale in-memory dict (decision.py may have
        # already removed the position).
        positions = await self.portfolio.get_positions()
        pos = next((p for p in positions if p["symbol"] == sym), None)
        units = pos["amount"] if pos else 0.0
        try:
            if self.mode != "paper":
                result = await self.twak.swap(units, sym, CASH_CURRENCY, slippage=0.5)
                tx_hash = result.get("tx_hash") or ""
            else:
                tx_hash = f"0xSELL_PAPER_{sym}"
            await self.portfolio.close_position(sym, price, tx_hash)
            logger.info("Forced sell OK: %s reason=%s price=%.4f tx=%s", sym, sell["reason"], price, tx_hash)
        except Exception as exc:
            logger.warning("Forced sell %s failed: %s", sym, exc)

    async def shutdown(self) -> None:
        """Graceful shutdown: log final state, close connections."""
        logger.info("Shutting down agent...")
        await self.trade_logger.close()
        await self.portfolio.close()
        await self.cache.close()
        await self.cmc.close()
        logger.info("Agent stopped. Total cycles: %d", self._cycle_count)

    async def dry_run(self, cycles: int = 1) -> list[dict[str, Any]]:
        """Run N cycles synchronously for testing."""
        await self.setup()
        results: list[dict[str, Any]] = []
        for i in range(cycles):
            logger.info("=== Dry-run cycle %d/%d ===", i + 1, cycles)
            results.append(await self.run_cycle())
        await self.shutdown()
        return results


def main() -> None:
    assert sys.version_info >= (3, 11), "Python 3.11+ required for asyncio.timeout"
    import argparse
    parser = argparse.ArgumentParser(description="CascadeFade Trading Agent")
    parser.add_argument("--mode", choices=["paper", "live"], default=os.getenv("AGENT_MODE", "paper"),
                      help="paper (log only) or live (execute swaps)")
    parser.add_argument("--cash", type=float, default=1000.0, help="Initial cash balance in USD")
    parser.add_argument("--cycles", type=int, default=0, help="Run N cycles and exit (0=loop forever)")
    parser.add_argument("--interval", type=int, default=TRADE_INTERVAL_MINUTES, help="Trade interval in minutes (default: 30)")
    args = parser.parse_args()

    agent = Agent(mode=args.mode, initial_cash=args.cash, interval_minutes=args.interval)

    if args.cycles > 0:
        results = asyncio.run(agent.dry_run(args.cycles))
        print(json.dumps(results, indent=2, default=str))
    else:
        asyncio.run(agent.main_loop())


if __name__ == "__main__":
    main()
