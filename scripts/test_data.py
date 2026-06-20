#!/usr/bin/env python3
"""Test CMC data fetching and caching."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cache import Cache
from src.cmc_client import CMCClient
from src.config import ALLOWLIST


async def main() -> None:
    cache = Cache()
    cmc = CMCClient()
    symbol_map = {k: "" for k in list(ALLOWLIST.keys())[:10]}

    print("Fetching quotes for:", list(symbol_map.keys()))
    quotes = await cmc.get_bulk_quotes(symbol_map)
    for sym, q in quotes.items():
        if "error" in q:
            print(f"  {sym}: ERROR — {q['error']}")
        else:
            print(f"  {sym}: ${q.get('price', 0):.4f} | 7d={q.get('percent_change_7d', 0):+.2f}% | 24h={q.get('percent_change_24h', 0):+.2f}%")
            await cache.set_quote(sym, q)

    print("\nFetching DEX trending...")
    trending = await cmc.get_dex_trending()
    print("  Trending:", trending[:5] if trending else "none / endpoint unavailable")

    print("\nFetching Fear & Greed...")
    fg = await cmc.get_fear_greed()
    if fg:
        print(f"  Fear & Greed: {fg['value']:.0f} ({fg['classification']})")
    else:
        print("  Fear & Greed: unavailable")

    await cache.close()
    await cmc.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
