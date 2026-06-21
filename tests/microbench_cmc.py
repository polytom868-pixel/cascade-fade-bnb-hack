"""Benchmark CMC REST client: latency, throughput, and payload sizes."""
import asyncio
import sys
sys.path.insert(0, "/home/eya/dorahack/bnbhack/velocis/track1-cascade-fade")

from src.cmc_client import CMCClient
from src.config import ALLOWLIST
from tests.microbench_core import MicroBenchmark, run_async


async def bench_cmc() -> list[dict]:
    results: list[dict] = []
    cmc = CMCClient(api_key=None)
    await cmc.connect()

    # 1. Session warm-up + get_bulk_quotes
    bench = await run_async("cmc.get_bulk_quotes", cmc.get_bulk_quotes(ALLOWLIST))
    results.append({
        **bench.as_dict(),
        "tokens_queried": len(ALLOWLIST),
        "note": "Bulk REST call + JSON parse",
    })

    # 2. get_dex_trending (may fail on free tier)
    try:
        bench2 = await run_async("cmc.get_dex_trending", cmc.get_dex_trending())
        results.append({
            **bench2.as_dict(),
            "note": "DEX trending endpoint",
        })
    except Exception as exc:
        results.append({
            "name": "cmc.get_dex_trending",
            "error": str(exc),
            "note": "Endpoint may require paid tier",
        })

    # 3. get_fear_greed
    try:
        bench3 = await run_async("cmc.get_fear_greed", cmc.get_fear_greed())
        results.append({
            **bench3.as_dict(),
            "note": "Fear & Greed index",
        })
    except Exception as exc:
        results.append({
            "name": "cmc.get_fear_greed",
            "error": str(exc),
            "note": "Endpoint may require paid tier",
        })

    # 4. Repeated bulk call (warm cache)
    bench4 = await run_async("cmc.get_bulk_quotes_cached", cmc.get_bulk_quotes(ALLOWLIST))
    results.append({
        **bench4.as_dict(),
        "tokens_queried": len(ALLOWLIST),
        "note": "Second call (connection reuse)",
    })

    # 5. Raw request round-trip on /v2/cryptocurrency/quotes/latest
    bench5 = await run_async("cmc._request quotes", cmc._request("GET", "/v2/cryptocurrency/quotes/latest", params={"symbol": "BNB"}))
    results.append({
        **bench5.as_dict(),
        "note": "Raw HTTP round-trip BNB",
    })

    await cmc.close()
    return results


if __name__ == "__main__":
    rows = asyncio.run(bench_cmc())
    for r in rows:
        print(r)
