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
from src.decision import CASH_CURRENCY, RISK_CURRENCY
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
        self.quoter = Quoter()
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

        # Verify BSC RPC
        if not self.quoter.w3.is_connected():
            if self.mode != "paper":
                logger.error("BSC RPC not connected — check BNB_RPC_URL")
                raise RuntimeError("Cannot start without BSC RPC")
            else:
                logger.warning("BSC RPC unavailable — running in paper mode, proceeding without on-chain data")
        else:
            logger.info("BSC RPC connected — block=%s", self.quoter.w3.eth.block_number)

        # Initialize portfolio cash
        await self.portfolio.initialize_cash(self.initial_cash)
        logger.info("Portfolio initialized: cash=$%.2f", self.initial_cash)

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
        logger.info("--- Cycle %d | %s ---", self._cycle_count, start.isoformat())

        # Fetch prices for ALL relevant tokens: held + basket + risk currency
        held_symbols = await self.portfolio.get_held_symbols()
        symbols_needed: set[str] = set(held_symbols)
        for tokens in NARRATIVE_BASKETS.values():
            symbols_needed.update(tokens)
        symbols_needed.add(RISK_CURRENCY)

        price_map: dict[str, float] = {}
        if symbols_needed:
            try:
                quotes = await self.cmc.get_bulk_quotes({s: "" for s in symbols_needed})
                price_map = {s: q.get("price", 0.0) for s, q in quotes.items()}
            except Exception as exc:
                logger.warning("CMC bulk quotes failed: %s", exc)

        # P1 #4: stop/take-profit check — generate forced sells before running decisions
        forced_sells = []
        positions = await self.portfolio.get_positions()
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

        cash = await self.portfolio.get_cash_balance()
        try:
            summary = await self.decision.run_cycle(cash, price_map)
        except Exception as exc:
            logger.exception("Cycle %d failed: %s", self._cycle_count, exc)
            summary = {"error": str(exc), "actions": {"buys": [], "sells": [], "holds": [], "rejections": []}, "notes": []}

        # Execute forced sells (stop-loss / take-profit)
        for sell in forced_sells:
            sym = sell["token"]
            price = sell["price"]
            pos = self.portfolio.positions.get(sym)
            units = pos["units"] if pos else 0.0
            if self.mode != "paper":
                swap_result = await self.twak.swap(units, sym, CASH_CURRENCY, slippage=0.5)
                tx_hash = swap_result.get("tx_hash") or ""
            else:
                tx_hash = f"0xSELL_PAPER_{sym}"
            await self.portfolio.close_position(sym, price, tx_hash)
            logger.info("Executed forced sell: %s reason=%s price=%.4f tx=%s", sym, sell["reason"], price, tx_hash)

        # Prepend forced sells to the decision's sell actions
        if forced_sells:
            summary.setdefault("actions", {})
            summary["actions"].setdefault("sells", [])
            summary["actions"]["sells"] = forced_sells + summary["actions"]["sells"]

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info("Cycle %d complete in %.1fs | actions=%s", self._cycle_count, elapsed, summary.get("actions", []))
        return summary

    async def main_loop(self) -> None:
        """Run trading loop until shutdown signal."""
        await self.setup()

        while not _shutdown_requested.is_set():
            try:
                await asyncio.wait_for(_shutdown_requested.wait(), timeout=self.interval.total_seconds())
            except asyncio.TimeoutError:
                pass

            if _shutdown_requested.is_set():
                break

            await self.run_cycle()
            await self.health_check()

        await self.shutdown()

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
