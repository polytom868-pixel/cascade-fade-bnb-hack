"""Benchmark SQLite I/O: portfolio writes, reads, cache ops, log writes."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, "/home/eya/dorahack/bnbhack/velocis/track1-cascade-fade")

from src.cache import Cache
from src.log import log_trade
from src.portfolio import Portfolio
from tests.microbench_core import MicroBenchmark, run_async


async def bench_storage() -> list[dict]:
    results: list[dict] = []

    tmpdir = tempfile.mkdtemp(prefix="cascade_bench_")
    db_path = os.path.join(tmpdir, "test.db")

    pf = Portfolio(db_path)

    # 1. init + schema creation
    bench1 = await run_async("portfolio.init", pf.init())
    results.append({**bench1.as_dict(), "note": "PRAGMAs + CREATE TABLE"})

    # 2. add_position (write)
    bench2 = await run_async(
        "portfolio.add_position",
        pf.add_position("INJ", 5.0, 0.8, "0xFAKE_TX_0"),
    )
    results.append({**bench2.as_dict(), "note": "Single INSERT"})

    # 3. add_position x20 batch
    with MicroBenchmark("portfolio.add_position_20x") as b3:
        for i in range(20):
            await pf.add_position(f"TK{i}", float(i), 1.0, f"0xFAKE_TX_{i}")
    results.append({
        **b3.result.as_dict(),
        "per_call_avg_ms": round(b3.result.wall_time_ms / 20, 3),
        "note": "20 independent INSERTs",
    })

    # 4. get_positions (read all)
    bench4 = await run_async("portfolio.get_positions", pf.get_positions())
    results.append({**bench4.as_dict(), "note": "SELECT all positions"})

    # 5. get_held_symbols
    bench5 = await run_async("portfolio.get_held_symbols", pf.get_held_symbols())
    results.append({**bench5.as_dict(), "note": "SELECT DISTINCT symbol"})

    # 6. log_trade sync write (to Python logger, no DB)
    bench6 = MicroBenchmark("log.log_trade")
    with bench6:
        for _ in range(100):
            log_trade("BUY", "INJ", 0.8, 5.0, 4.0, tx_hash="0xTEST")
    results.append({
        **bench6.result.as_dict(),
        "per_call_avg_ms": round(bench6.result.wall_time_ms / 100, 3),
        "note": "100x sync logger.info calls",
    })

    # 7. Cache set + get
    cache = Cache(db_path=db_path.replace(".db", "_cache.db"))
    await cache.connect()
    bench7 = await run_async("cache.set_get", _cache_ops(cache))
    results.append({**bench7.as_dict(), "note": "Cache SET + GET round-trip"})
    await cache.close()

    await pf.close()
    return results


async def _cache_ops(cache) -> None:
    await cache.set("BNB", {"price": 590.0, "ts": 0})
    await cache.get("BNB")


if __name__ == "__main__":
    rows = asyncio.run(bench_storage())
    for r in rows:
        print(r)
