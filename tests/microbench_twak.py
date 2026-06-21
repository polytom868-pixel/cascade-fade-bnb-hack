"""Benchmark TWAK subprocess overhead."""
import asyncio
import os
import sys

sys.path.insert(0, "/home/eya/dorahack/bnbhack/velocis/track1-cascade-fade")

from src.twak import TWAKExecutor
from tests.microbench_core import MicroBenchmark, run_async


async def bench_twak() -> list[dict]:
    results: list[dict] = []
    twak = TWAKExecutor(password=os.getenv("TWAK_WALLET_PASSWORD", ""))

    # 1. wallet_address (subprocess + parse)
    bench1 = await run_async("twak.wallet_address", twak.wallet_address())
    results.append({
        **bench1.as_dict(),
        "note": "twak wallet address --chain bsc --json",
    })

    # 2. get_balances (subprocess + parse)
    try:
        bench2 = await run_async("twak.get_balances", twak.get_balances())
        results.append({
            **bench2.as_dict(),
            "note": "twak wallet balance --chain bsc --json",
        })
    except Exception as exc:
        results.append({
            "name": "twak.get_balances",
            "error": str(exc),
            "note": "TWAK balance call",
        })

    # 3. quote swap (quote-only, no signature)
    try:
        bench3 = await run_async(
            "twak.quote_swap",
            twak.swap(1.0, "BNB", "USDT", quote_only=True),
        )
        results.append({
            **bench3.as_dict(),
            "note": "twak swap --quote-only (BSC RPC round-trip)",
        })
    except Exception as exc:
        results.append({
            "name": "twak.quote_swap",
            "error": str(exc),
            "note": "May need funded wallet + RPC",
        })

    return results


if __name__ == "__main__":
    rows = asyncio.run(bench_twak())
    for r in rows:
        print(r)
