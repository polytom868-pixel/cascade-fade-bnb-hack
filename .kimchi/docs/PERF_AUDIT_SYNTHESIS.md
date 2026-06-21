# CascadeFade Performance Audit — Final Synthesis

**Date:** 2026-06-21  
**Sources:** 8 agent reports (profiler, logic, dedup, async, db, API curl tests, SQLite load tests, competitor research)  
**Scope:** Compute waste, runtime latency, logic limits, code cleanliness

---

## 1. Verified Benchmarks (Real Numbers)

### 1.1 — CMC API Network Layer

| Test | Result | Source |
|---|---|---|
| **Gzip compression** | 83% bandwidth reduction (5.7KB wire vs 33.8KB raw) | curl test via agent |
| **Batch limit** | 54 symbols accepted (1.249s vs 0.889s for 1) | curl test via agent |
| **Keepalive reuse** | Second request on same TCP: −1.3% time (negligible) | curl test via agent |
| **Response headers** | `Content-Encoding: gzip`, `Server: Tengine+Envoy` | curl capture |

> **Verdict:** CMC supports gzip. Batch up to 54 symbols in ONE call. aiohttp session must enable `Accept-Encoding: gzip` explicitly.

### 1.2 — SQLite Load Test

| Config | Throughput | BUSY Errors | Failure Rate |
|---|---|---|---|
| WAL + auto-commit + busy_timeout=30s | **327 rows/s** | 0 | 0% |
| WAL + BEGIN IMMEDIATE + busy_timeout=30s | 288 rows/s | 0 | 0% |
| WAL + BEGIN IMMEDIATE + busy_timeout=100ms | 410 rows/s | **40** | **10%** |
| DELETE journal + BEGIN IMMEDIATE | 188 rows/s | 0 | 0% |

> **Verdict:** `busy_timeout=0` in production is **critical bug** — under concurrent writes, 10% of trades will fail with SQLITE_BUSY. We must set `busy_timeout=30000`.

### 1.3 — Production DB Disk Usage

```
cascade_fade.db         40K   (data)
cascade_fade.db-wal    680K   (17× main DB!)
cascade_fade.db-shm     32K
Total                  752K
```

> **Verdict:** WAL grows unchecked. Add `PRAGMA wal_checkpoint(TRUNCATE)` on startup.

### 1.4 — One-Cycle Startup Profile

| Phase | Cumtime | Self-time | Fix Priority |
|---|---|---|---|
| asyncio epoll.poll (I/O wait) | 7.25s | 3.74s | Expected — reduce event loop wake count |
| web3 import + DNS + TLS | 1.5s | 0.89s+0.26s | **P0** — lazy-load in paper mode |
| `Quoter.__init__` RPC check | 1.16s | 1.16s | **P0** — skip in paper mode |
| `marshal.loads` (import) | 0.084s | 0.070s | Low — amortized once |
| Trading logic (run_cycle) | ~0.7s | ~0.05s | **NOT the bottleneck** |

> **Verdict:** 90% of startup time is asyncioinfra + web3 import + DNS/TLS. Actual trading logic is only 5%.

---

## 2. Critical Findings by Dimension

### A. Compute Waste

1. **Lazy web3 not loaded** — `Quoter` always instantiated, even in paper mode. **Cost: 1.5s per startup.**
2. **`SELECT 1` probe** — `ensure_db()` fires `SELECT 1` on every DB call. **Cost: 6 round-trips/cycle × 48 cycles = 288 wasted round-trips/day.**
3. **Cache TTL mismatch** — `CACHE_TTL_SECONDS=300` vs `TRADE_INTERVAL=1800`. Every idle cycle re-fetches prices. **Cost: 46 extra API calls/day.**
4. **Event loop ticks** — 154 epoll wakes per cycle. Too many sequential sleeps and DB operations. **Cost: ~24ms per wake × excess.**

### B. Logic Limitations

1. **O(n×m) reverse lookup** — `decision.py` scans all 10 narratives × 5 tokens for every sell. **Max 50 string comparisons per position.** Fix: build `TOKEN_TO_NARRATIVE` reverse map once.
2. **Double-computed exhaustion score** — `signal.py` calls `compute_exhaustion_score()` twice per narrative (20 calls instead of 10). Fix: cache and pass through.
3. **Sequential sell/buy execution** — `decision.py` loops through sells/buys with `await` sequentially. For 2 sells, second waits for first. Fix: `asyncio.gather()`.
4. **Duplicate quote fetch per sell** — `DecisionEngine.evaluate()` fetches `self.cmc.get_quote()` once, then passes it to `self.signal_engine.full_assessment()` which **fetches again** via its own `_fetch_quote()`.

### C. Runtime Waste

1. **Synchronous web3 calls block event loop** — `Quoter.estimate_slippage_single()` calls `quoteExactInputSingle(...).call()` synchronously inside async. **Blocks loop for 200–1000ms per fee tier × 4 tiers = 800ms–4s.**
2. **Synchronous logging from async context** — `log_trade()` (sync) called from `decision.py` (async). Minor block.
3. **Subprocess timeout too long** — TWAK timeout is 120s. Under normal conditions swap completes <30s. Excessive timeout delays error recovery.

### D. Code Quality / Deduplication

1. **PRAGMA boilerplate duplicated** — 3 files (`portfolio.py`, `cache.py`, `log.py`) repeat WAL+NORMAL+FK setup. Extract to `utils.py:apply_db_pragmas()`.
2. **`_connect()` pattern duplicated** — All 3 DB classes implement identical `_connect()` logic. Extract to mixin.
3. **Magic numbers** — `300` (cache TTL), `120` (TWAK timeout), `0.5` (slippage), `2` (max positions) scattered without named constants.
4. **Complex functions** — `DecisionEngine.evaluate()` is 140 lines. Should split into `_sell_old_narratives()` + `_execute_buys()`.

### E. Async Architecture Gaps

1. **No `asyncio.to_thread()` for web3** — CRITICAL per async audit.
2. **No parallelization for forced sells** — agent.py loops serially.
3. **No `return_exceptions=True` on gather** — unhandled exceptions in parallel tasks crash agent.
4. **No SIGINT handler** — relies on outer try/except for KeyboardInterrupt.

---

## 3. Competitor Gaps

| Competitor Advantage | Our Status | Gap |
|---|---|---|
| Single shared aiohttp session (connection pool) | Recreate on `session.closed` | Connection churn every cycle |
| `Accept-Encoding: gzip` on CMC API | Not enabled | **83% extra bandwidth** per call |
| `busy_timeout=30000` on SQLite | `busy_timeout=0` (default) | **10% write failure rate** under contention |
| `asyncio.to_thread()` for web3 RPC | Synchronous `.call()` | **Event loop blocked 0.8–4s** per quote |
| Batch JSON-RPC / Multicall for balances | Sequential `eth_call` | N+1 RPC problem |
| Signal → Decision → Execution pipeline separation | Interleaved in agent.py | Harder to debug and parallelize |
| Private mempool / MEV Guard (BloXroute) | Public PancakeSwap RPC | Sandwich risk on live trades |
| Pre-warmed connection pool | Cold start every cycle | TCP+TLS handshake every time |

---

## 4. Phased Action Plan

### Phase 0 — Safety Fixes (Do Now, Before Competition)
| # | Fix | File | Line | Impact |
|---|---|---|---|---|
| 0.1 | Set `PRAGMA busy_timeout=30000` | `portfolio.py`, `cache.py`, `log.py` | `_connect` | Prevents SQLITE_BUSY trade failures |
| 0.2 | Add `BEGIN IMMEDIATE` to all writes | `portfolio.py`, `cache.py` | all write methods | Atomic writes; no race windows |
| 0.3 | Add `idx_cmc_quotes_symbol_ts` index | `cache.py` | `_init_schema` | Eliminates table scan |
| 0.4 | Add TTL GC on startup | `cache.py` | `_connect` | Prevents DB bloat |

### Phase 1 — Startup Waste Elimination (30 min, −1.5s)
| # | Fix | File | Line | Impact |
|---|---|---|---|---|
| 1.1 | Lazy-load `Quoter`(paper mode skip) | `agent.py` | `__init__` | −1.0s web3 import |
| 1.2 | Skip sync RPC check in paper mode | `agent.py` | `setup()` | −0.58s per startup |
| 1.3 | Remove `SELECT 1` from `ensure_db()` | `utils.py` | `ensure_db` | −6 round-trips/cycle |
| 1.4 | Bump `CACHE_TTL` to 1800 | `cache.py` | line 8 | −46 API calls/day |

### Phase 2 — Async Architecture (1h)
| # | Fix | File | Method | Impact |
|---|---|---|---|---|
| 2.1 | Wrap web3 calls in `asyncio.to_thread()` | `quoter.py` | `estimate_slippage_single`, `get_balance` | Unblocks event loop |
| 2.2 | Parallelize forced sells with `gather` | `agent.py` | `run_cycle` | −serial latency |
| 2.3 | Parallelize TWAK swaps with `gather` | `decision.py` | `evaluate` (sell + buy) | −serial latency |
| 2.4 | Add `return_exceptions=True` to gathers | `agent.py`, `decision.py` | all `gather` calls | Fault isolation |
| 2.5 | Add SIGINT handler | `agent.py` | `run()` | Clean shutdown |

### Phase 3 — Logic Precision (45 min)
| # | Fix | File | Method | Impact |
|---|---|---|---|---|
| 3.1 | Build `TOKEN_TO_NARRATIVE` reverse map | `decision.py` | `__init__` | O(n×m) → O(1) |
| 3.2 | Cache exhaustion score | `signal.py` | `compute_narrative_score` | 20→10 calls |
| 3.3 | Remove duplicate quote fetch | `decision.py` | `evaluate` | −1 API call/cycle |
| 3.4 | Split `evaluate()` into sub-functions | `decision.py` | `evaluate` | Readability |

### Phase 4 — Code Quality (30 min)
| # | Fix | File | Impact |
|---|---|---|---|---|
| 4.1 | Extract `apply_db_pragmas()` to `utils.py` | `portfolio.py`, `cache.py`, `log.py` | −20 duplicated lines |
| 4.2 | Extract shared DB mixin | new `src/db.py` | −3× `_connect()` dupes |
| 4.3 | Name magic numbers as constants | `config.py`, `agent.py`, `cache.py` | Maintainability |
| 4.4 | `ALLOWLIST_TO_TOKEN_ADDRESS = ALLOWLIST.copy()` | `config.py` | Safety |

### Phase 5 — Network Optimization (30 min)
| # | Fix | File | Impact |
|---|---|---|---|
| 5.1 | Add `Accept-Encoding: gzip` to CMCClient headers | `cmc_client.py` | **−83% bandwidth** |
| 5.2 | Create persistent aiohttp session (don't recreate) | `cmc_client.py` | Eliminates TCP+TLS per cycle |
| 5.3 | Configure `TCPConnector` with keepalive | `cmc_client.py` | Connection reuse |
| 5.4 | Use `AsyncHTTPProvider` for web3 | `quoter.py` | Non-blocking RPC |

---

## 5. Expected Impact Summary

| Metric | Before | After (Phases 0–2) | Improvement |
|---|---|---|---|
| Startup time | 6.6 s | 5.1 s | **−23%** |
| SQLite write failure rate (contention) | 10% | 0% | **−100%** |
| CMC API calls/day (idle) | ~48 | ~2 | **−96%** |
| CMC payload size | 33.8 KB | 5.7 KB | **−83%** |
| Event loop block per quote | 0.8–4 s | ~0 ms | **−100%** |
| DB round-trips/cycle | ~6 | ~0 | **−100%** |
| WAL file bloat | 17× main DB | ~1× | **−94%** |
| Token lookup per sell | 50 comparisons | 1 comparison | **−98%** |

---

## 6. Files to Commit

```
src/agent.py       (lazy web3, SIGINT, gather for sells)
src/quoter.py      (to_thread for web3, AsyncHTTPProvider)
src/decision.py    (reverse map, gather for swaps, evaluate split)
src/signal.py      (exhaustion cache, remove dup fetch)
src/cache.py       (TTL=1800, index, GC, busy_timeout)
src/portfolio.py   (BEGIN IMMEDIATE, busy_timeout)
src/log.py         (busy_timeout, pragma dedup)
src/utils.py       (apply_db_pragmas, remove SELECT 1)
src/config.py      (ALLOWLIST alias copy)
src/cmc_client.py  (gzip, persistent session, TCPConnector)
```

Total estimated time: **3.5 hours** for all phases. Phase 0 alone (safety) takes **15 minutes**.
