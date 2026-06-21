"""Benchmark signal engine: CPU time & memory per narrative evaluation."""
import sys
sys.path.insert(0, "/home/eya/dorahack/bnbhack/velocis/track1-cascade-fade")

import asyncio

from src.cmc_client import CMCClient
from src.signal import SignalEngineClass
from tests.microbench_core import MicroBenchmark, run_async


async def bench_signal() -> list[dict]:
    results: list[dict] = []

    cmc = CMCClient(api_key=None)
    await cmc.connect()

    # Use real price map for richer evaluation
    price_map = await cmc.get_bulk_quotes({"BNB": ""})

    sig = SignalEngineClass(cmc)

    # 1. _fetch_narrative_data (CMC + aggregation)
    bench1 = await run_async("signal._fetch_narrative_data", sig._fetch_narrative_data())
    results.append({
        **bench1.as_dict(),
        "note": "Fetch + basket aggregation",
    })

    # 2. evaluate() full cycle
    # Populate day so conviction_history has data
    sig.day = 1
    bench2 = await run_async("signal.evaluate", sig.evaluate())
    results.append({
        **bench2.as_dict(),
        "note": "Full signal evaluate (regime + global_scan)",
    })

    # 3. evaluate() 10x amortised cost (cache effects)
    with MicroBenchmark("signal.evaluate_10x") as b3:
        for _ in range(10):
            await sig.evaluate()
    results.append({
        **b3.result.as_dict(),
        "per_call_avg_ms": round(b3.result.wall_time_ms / 10, 3),
        "note": "10 sequential evaluations",
    })

    await cmc.close()
    return results


if __name__ == "__main__":
    rows = asyncio.run(bench_signal())
    for r in rows:
        print(r)
