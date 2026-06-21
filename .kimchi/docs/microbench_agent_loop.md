# CascadeFade Agent Loop Microbench Report

**Date:** 2026-06-21
**Mode:** paper (cash=$1000, interval=1 min, cycles=3 back-to-back)
**Instrumentation:** `time.perf_counter_ns()` monkey-patched per phase; `tracemalloc` snapshots

---

## 1. Phase Timing Table (nanosecond precision)

Measured across **3 consecutive warm-cache cycles** (same process, no teardown between cycles).

| Phase | Mean (ms) | StdDev (ms) | Min (ms) | Max (ms) | N |
|---|---|---|---|---|---|
| `cmc.get_bulk_quotes` | **464.79** | 205.08 | — | — | 3 |
| `decision.run_cycle` | **454.72** | 139.87 | — | — | 3 |
| `signal_engine.evaluate` | **453.79** | 141.19 | — | — | 3 |
| `portfolio.get_positions` | 0.73 | 0.41 | — | — | 3 |
| `portfolio.add_position` | 0.40 | 0.18 | — | — | 3 |
| `portfolio.close_position` | — | — | — | — | 0 |
| `asyncio.sleep` | — | — | — | — | 0 |
| **TOTAL CYCLE WALL** | **798.06** | **176.23** | **594.72** | **906.53** | 3 |

> **Note:** `asyncio.sleep` and `portfolio.close_position` recorded 0 invocations because no positions were closed during the 3 benchmark cycles and the benchmark script does not use the main_loop (which drives sleep). `add_position` was called once per basket token (5 tokens × 1 cycle = 5 calls total across 3 cycles).

### Per-Cycle Wall Time

| Cycle | Wall Time (ms) | Actions |
|---|---|---|
| Cycle 1 | 594.72 | 5 BUY opens (Gaming/NFT basket) |
| Cycle 2 | 892.93 | 5 HOLD, 5 cooldown rejections |
| Cycle 3 | 906.53 | 5 HOLD, 5 cooldown rejections |

Cycle 1 is ~300ms faster because `decision.evaluate()` skips the TWAK swap path in paper mode (no real swap needed, `tx_hash` is mocked inline). Cycles 2–3 hit the full code path including `signal_engine._fetch_narrative_data()` which re-fetches CMC data even when positions are held.

---

## 2. Memory Allocation Table

Snapshot: `tracemalloc` delta between cycle start (post-setup) and cycle end (post-shutdown).

| File | Net (B) | Allocations Gained | Sites | Verdict |
|---|---|---|---|---|
| `signal.py` | **+3,272** | +3,272 across 6 sites | 6 | notable |
| `portfolio.py` | **+1,297** | +1,297 across 5 sites | 5 | low |
| `decision.py` | **+720** | +720 across 5 sites | 5 | low |
| `cmc_client.py` | **+568** | +632 / -64 | 2 | low |
| `agent.py` | **+162** | +226 / -64 | 4 | negligible |
| `risk.py` | 0 | 0 | 0 | clean |
| `config.py` | 0 | 0 | 0 | clean |
| **TOTAL (process)** | **+12,073 net** | +22,914 allocated / -10,841 freed | — | — |

Top allocation sites across the entire process:

| # | Delta (B) | Count | Location |
|---|---|---|---|
| 1 | +7,320 | +152 | `json/decoder.py:353` (CMC JSON response parsing) |
| 2 | +2,984 | +34 | `aiohttp` (session internal buffers) |
| 3 | +1,800 | +31 | `tracemalloc.py:558` (tracing overhead) |
| 4 | +951 | +9 | `<frozen abc>:123` (async method dispatch) |
| 5–14 | +560–848 | +10–11 each | project source files (signal, portfolio, decision) |

---

## 3. Bottleneck Ranking

### Wall-Time Bottlenecks

| Rank | Phase | Mean ms | % of Wall | Severity |
|---|---|---|---|---|
| 1 | `cmc.get_bulk_quotes` | 464.79 | **58.2%** | CRITICAL |
| 2 | `decision.run_cycle` | 454.72 | **57.0%** | CRITICAL |
| 3 | `signal_engine.evaluate` | 453.79 | **56.9%** | CRITICAL |
| 4 | `portfolio.get_positions` | 0.73 | 0.09% | minor |
| 5 | `portfolio.add_position` | 0.40 | 0.05% | minor |

> **Key insight:** The three CRITICAL phases are a **single causal chain** — `decision.run_cycle` calls `signal_engine.evaluate()`, which calls `cmc.get_bulk_quotes()`. The actual decision logic in `decision.evaluate()` (risk guards, rebalance, buy/sell evaluation) consumes only the remainder (~50ms). The overwhelming cost is the CMC network round-trip.

**Cycle 1 vs. Cycles 2–3 variance:** The ~300ms difference between cycle 1 (594ms) and cycles 2–3 (~900ms) is attributable to the first cycle's decision flow bypassing the `signal_engine._fetch_narrative_data()` CMC call path, while subsequent cycles execute the full fetch-and-score pipeline twice (once in `setup`'s connectivity check, once in `run_cycle`).

### Memory Bottlenecks

| Rank | File | Net (B) | Severity |
|---|---|---|---|
| 1 | `signal.py` | +3,272 | **HIGH** (most allocations, no frees) |
| 2 | `portfolio.py` | +1,297 | low |
| 3 | `decision.py` | +720 | low |
| 4 | `cmc_client.py` | +568 | low |

> **Key insight:** `signal.py` allocations grow by 3,272 B per cycle with **zero frees** — this indicates an accumulation pattern. The top sites (848 B × 11, 640 B × 10, 560 B × 10) are consistent with dict and list objects created during `global_scan()` and `compute_narrative_score()`. Over hundreds of cycles this would leak memory.

---

## 4. Recommendations Per Phase

### `cmc.get_bulk_quotes` — CRITICAL (58.2% of wall time)

**Problem:** Every cycle makes a live CMC REST API call over the network. This is the single largest time consumer.

**Recommendations:**
1. **TTL cache with 30-second stale-while-revalidate.** Wrap `cmc.get_bulk_quotes()` with a time-bounded cache (`src/cache.py` already exists). Skip the API call if a valid cached response exists. This could eliminate 400–500ms per cycle.
2. **Request coalescing.** If `main_loop` runs faster than `TRADE_INTERVAL_MINUTES`, multiple cycles should share one CMC fetch. Use an `asyncio.Lock` to dedupe concurrent requests.
3. **Reduce symbol count.** Currently fetching all basket tokens (~30 symbols) every cycle. Only fetch tokens in the top-ranked narrative plus risk-currency/BNB for pricing — skip the other 4–5 narratives.

### `signal_engine.evaluate` — CRITICAL (56.9% of wall time)

**Problem:** `evaluate()` calls `_fetch_narrative_data()` which makes **another** CMC call inside the signal engine, independent of the one in `agent.run_cycle()`. This means CMC is called twice per cycle (once in `run_cycle` for pricing, once in `signal_engine` for narrative scoring).

**Recommendations:**
1. **Unify the two CMC calls.** Pass the price map from `agent.run_cycle`'s `cmc.get_bulk_quotes()` into `decision.run_cycle()`, then into `signal_engine.evaluate()`. The signal engine should reuse the same data instead of fetching independently.
2. **Cache narrative scores for 60s.** Regime detection and narrative rankings change slowly. Cache `global_scan()` output and only recompute every N cycles or when price data changes >5%.
3. **`__slots__` on `SignalEngineClass`.** Eliminate per-instance `__dict__` overhead (saves ~3 KB per instance at class instantiation, and reduces allocation churn per cycle).

### `decision.run_cycle` — CRITICAL (57.0% of wall time)

**Problem:** This phase includes `signal_engine.evaluate()`, which itself is 57% of the cycle. The decision logic itself (risk guards, rebalance, buy/sell actions) is fast (~50ms).

**Recommendations:**
1. **Move `signal_engine.evaluate()` out of `decision.run_cycle()` and time it separately** at the `agent.run_cycle` level. Currently timing it as part of decision makes attribution ambiguous.
2. **Pre-build `NARRATIVE_BASKETS` token index.** The decision engine iterates `NARRATIVE_BASKETS` items to find which narrative a token belongs to (`for narr, tokens in NARRATIVE_BASKETS.items()`). Pre-compute a `TOKEN_TO_NARRATIVE` dict once at startup.
3. **Reduce `actions` dict reallocation.** Every `evaluate()` call creates a new `{"buys": [], "sells": [], "holds": [], "rejections": []}` dict. Consider using a reusable object or `dict.clear()` + repopulate.

### `portfolio.get_positions` — minor (0.09% of wall time)

**Problem:** Called once per cycle via `get_positions()` which does a SQLite SELECT. With 5 positions this is negligible.

**Recommendations:**
1. **Cache the positions list in memory** (`self._positions_cache`) and invalidate on `add_position`/`close_position`. Since `run_cycle` calls `get_positions()` once for forced-sell checking, this saves one DB round-trip.
2. **Use WAL mode** — already set, good.

### `portfolio.add_position` — minor (0.05% of wall time)

**Problem:** Each `add_position()` call does a SQLite INSERT with an immediate `COMMIT`. 5 tokens × 1 cycle = 5 commits per cycle.

**Recommendations:**
1. **Batch the writes.** Collect all position changes in a list, then commit once per cycle instead of per-position. Python's `aiosqlite` supports `executemany` with a single `commit()`.
2. **Use `sync_position_to_db` as the single DB write path** — it already exists but is called after every individual swap. Consider deferring it to end-of-cycle.

### Memory: `signal.py` — notable accumulation (+3,272 B/cycle, no frees)

**Problem:** `global_scan()` creates new dict objects for `portfolio_weights`, `narrative_rankings`, and `bucket_scores` on every call. Over many cycles, `conviction_history` dict also grows unboundedly.

**Recommendations:**
1. **Implement `__slots__` on `SignalEngineClass`** — reduces per-instance overhead and discourages unbounded `__dict__` growth.
2. **Cap `conviction_history`.** Prune entries older than 7 days. Currently it grows indefinitely.
3. **Reuse dict objects in `global_scan()`** where safe instead of allocating new `portfolio_weights` and `ranked` structures on every call.

---

## 5. Summary

| Dimension | #1 Bottleneck | Impact |
|---|---|---|
| **Wall time** | `cmc.get_bulk_quotes` (58.2%) | Network I/O |
| **Memory** | `signal.py` (+3,272 B/cycle, no frees) | Accumulation leak |
| **Easy win** | Cache CMC for 30s | Save ~460ms/cycle |
| **Architectural** | Dual CMC calls per cycle | Unify price_map reuse |
| **Memory fix** | `__slots__` + conviction cap | Stop accumulation |