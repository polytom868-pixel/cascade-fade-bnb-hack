#!/usr/bin/env python3
"""Test signal evaluation on live or synthetic CMC data."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cache import Cache
from src.cmc_client import CMCClient
from src.config import ALLOWLIST
from src.quoter import Quoter
from src.signal import SignalEngine


async def main() -> None:
    cache = Cache()
    cmc = CMCClient()
    signal = SignalEngine()
    quoter = Quoter()

    # Fetch quotes
    symbols = list(ALLOWLIST.keys())[:20]
    print(f"Fetching {len(symbols)} quotes...")
    quotes = await cmc.get_bulk_quotes({k: "" for k in symbols})

    # Fetch trending
    trending = await cmc.get_dex_trending()
    print(f"Trending: {trending[:5]}")

    # Fear & greed
    fg = await cmc.get_fear_greed()
    fg_class = (fg or {}).get("classification", "Neutral")
    print(f"Fear & Greed: {fg_class}")

    # Build slippage map (BNB → each token, small amount)
    slippage_map = {}
    for sym in symbols:
        addr = ALLOWLIST.get(sym)
        q = quoter.estimate_slippage_single("BNB", sym, 5.0,
                                            from_addr=ALLOWLIST.get("BNB"), to_addr=addr)
        slippage_map[sym] = q.get("slippage_pct", 1.0)

    # Evaluate buys
    held = []
    candidates = signal.find_candidates(quotes, trending, held, fg, slippage_map)
    print(f"\n=== BUY CANDIDATES ({len(candidates)}) ===")
    for c in candidates[:5]:
        print(f"  {c.symbol}: conf={c.confidence:.2f} | {c.reason}")

    # Evaluate sells (simulate held positions)
    print("\n=== SELL CHECKS (simulated) ===")
    test_positions = [
        {"symbol": "CAKE", "entry_price": 2.0, "entry_ts": "2026-06-19T00:00:00+00:00"},
        {"symbol": "ETH", "entry_price": 3000.0, "entry_ts": "2026-06-19T00:00:00+00:00"},
    ]
    for pos in test_positions:
        quote = quotes.get(pos["symbol"], {})
        sell = signal.evaluate_sell(
            pos["symbol"], quote, pos["entry_price"], pos["entry_ts"],
            trending, hours_held=24.0, portfolio_drawdown_pct=0.05,
        )
        print(f"  {pos['symbol']}: {sell.action} — {sell.reason}")

    await cache.close()
    await cmc.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
