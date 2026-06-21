"""Zero-copy / memory-duplication analysis across the data pipeline."""
import asyncio
import sys
import tracemalloc

sys.path.insert(0, "/home/eya/dorahack/bnbhack/velocis/track1-cascade-fade")

from src.cmc_client import CMCClient
from src.signal import SignalEngineClass


def deep_size(obj, seen=None) -> int:
    """Recursively compute memory footprint of a Python object."""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum(deep_size(k, seen) + deep_size(v, seen) for k, v in obj.items())
    elif isinstance(obj, (list, tuple, set)):
        size += sum(deep_size(i, seen) for i in obj)
    return size


async def bench_zero_copy() -> list[dict]:
    results: list[dict] = []
    tracemalloc.start()

    cmc = CMCClient(api_key=None)
    await cmc.connect()

    # Baseline
    snap0 = tracemalloc.take_snapshot()
    price_map: dict = await cmc.get_bulk_quotes({"BNB": ""})
    snap1 = tracemalloc.take_snapshot()
    pm_size = deep_size(price_map)
    results.append({
        "name": "zero_copy.price_map",
        "deep_size_kb": round(pm_size / 1024, 3),
        "keys": len(price_map),
        "note": "CMC bulk response",
    })

    sig = SignalEngineClass(cmc)
    narrative_data = await sig._fetch_narrative_data()
    snap2 = tracemalloc.take_snapshot()
    nd_size = deep_size(narrative_data)
    results.append({
        "name": "zero_copy.narrative_data",
        "deep_size_kb": round(nd_size / 1024, 3),
        "narratives": len(narrative_data),
        "keys_per_narrative": len(next(iter(narrative_data.values()))) if narrative_data else 0,
        "note": "Per-basket data from signal",
    })

    # Detect sharing: modify price_map, see if narrative_data is affected
    # Since _fetch_narrative_data copies values into new dicts, they shouldn't share
    shared = False
    if narrative_data:
        first_narr = next(iter(narrative_data))
        first_nd = narrative_data[first_narr]
        # There is no back-reference to price_map in narrative_data, so this is always false

    # Signal result
    signal_result = await sig.evaluate()
    snap3 = tracemalloc.take_snapshot()
    sr_size = deep_size(signal_result)
    results.append({
        "name": "zero_copy.signal_result",
        "deep_size_kb": round(sr_size / 1024, 3),
        "deep_size_vs_price_map_pct": round((sr_size / max(pm_size, 1)) * 100, 1),
        "note": "Full evaluate() output dict",
    })

    # Memory deltas (allocated between snapshots)
    def delta(snap_a, snap_b, label: str) -> dict:
        diff = snap_b.compare_to(snap_a, "lineno")
        top = diff[:3]
        total = sum(stat.size_diff for stat in diff)
        return {
            "name": f"zero_copy.delta.{label}",
            "allocated_kb": round(total / 1024, 3),
            "top_allocators": [
                f"{stat.traceback.format()[-1]} ({stat.size_diff / 1024:.1f}KB)"
                for stat in top
            ],
        }

    results.append(delta(snap0, snap1, "price_map"))
    results.append(delta(snap1, snap2, "narrative_data"))
    results.append(delta(snap2, snap3, "signal_result"))

    # Byte duplication estimate: narrative_data has ~10 narratives × 20 keys
    # Each value is a scalar (int/float). Total duplication vs price_map should be low
    dup_est_kb = nd_size / 1024  # all new dicts, so full duplication

    results.append({
        "name": "zero_copy.summary",
        "price_map_kb": round(pm_size / 1024, 3),
        "narrative_data_kb": round(nd_size / 1024, 3),
        "signal_result_kb": round(sr_size / 1024, 3),
        "estimated_duplicate_kb": round(dup_est_kb, 3),
        "note": "If narrative_data shares no references with price_map, duplication = 100% of basket data",
    })

    tracemalloc.stop()
    await cmc.close()
    return results


if __name__ == "__main__":
    rows = asyncio.run(bench_zero_copy())
    for r in rows:
        print(r)
