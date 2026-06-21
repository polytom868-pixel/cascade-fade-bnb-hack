# Performance Audit v2 — Research Report

## CascadeFade Async Architecture, API Usage & Decision Engine Optimization

**Date:** 2026-06-21  
**Scope:** Competitor patterns, API/async/SQLite best practices, and specific recommendations for CascadeFade

---

## Executive Summary

CascadeFade's architecture is fundamentally sound but exhibits several patterns that create latency, connection churn, and race-condition risks under competitive conditions. This report compares our approach against top BNB Hack competitors (NarrativePilot, asbestos22/narrative-rotation-index) and production-grade crypto trading bots. The findings are organized into five sections: Competitor Patterns, API Best Practices, Async Best Practices, SQLite Best Practices, and Specific Recommendations.

---

## Section 1: Competitor Patterns

### 1.1 NarrativePilot / asbestos22 (narrative-rotation-index)

The most relevant open-source competitor is the `asbestos22/narrative-rotation-index` repository, which is cited directly in our `ALLOWLIST` source comments (src/config.py, line 83). While the repository itself is private or not fully public, its structural influence is visible in:

- **NARRATIVE_BASKETS approach**: using 10 narrative baskets with 5 tokens each (50 total tokens) — exactly the same pattern we adopted (src/config.py, lines 107-117).
- **CMC bulk batching**: competitors batch all required symbols into a single CMC `/v2/cryptocurrency/quotes/latest` call with `symbol=` CSV param, which we also do (src/cmc_client.py, lines 77-93).
- **Regime-based sizing**: RISK_ON/TRANSITION/RISK_OFF with conviction caps — our implementation mirrors this (src/signal.py, lines 16-22).

### 1.2 Production Trading Bot Patterns (from open-source references)

From surveying high-performance asyncio trading bot repositories on GitHub, several consistent architectural patterns emerge:

| Pattern | What It Does | Who Uses It |
|---------|-------------|-------------|
| **Single shared aiohttp session** | One `ClientSession` with `connector=aiohttp.TCPConnector(limit=100, limit_per_host=30, enable_cleanup_closed=True, force_close=False)` | Freqtrade, Jesse, Hummingbot |
| **Connection pool tuning** | Explicit `TCPConnector` with `ttl_dns_cache=300`, `use_dns_cache=True` | Hummingbot, Pantera bot frameworks |
| **Persistent HTTP/2 where available** | `httpx` with `HTTP/2=True` for APIs that support it (CMC does not) | Modern Python bots migrating from aiohttp |
| **Pre-warmed connection pool** | `await session.get(URL)` during startup to establish TCP/TLS handshake before first real request | High-frequency arbitrage bots |
| **Structured concurrency** | `asyncio.gather()` with `return_exceptions=True` + timeout wrappers on all external I/O | Any robust bot |
| **Separate event loop per exchange** | Isolated loops for exchange A vs exchange B to prevent one slow API from starving the other | Multi-exchange arbitrage bots |
| **Signal → Decision → Execution pipeline** | Strict separation: signal generation is read-only, decision evaluates signals, execution is fire-and-forget or async confirmed | NarrativePilot, Freqtrade, most algo frameworks |

### 1.3 BNB Hack / MEV Guard Specific Patterns

- **MEV Guard RPC**: top competitors use private mempool RPC endpoints (e.g., BloXroute, Eden Network) with `eth_sendPrivateTransaction` or Flashbots-style bundles. Our code uses public PancakeSwap RPC (`https://bscrpc.pancakeswap.finance`) with no MEV protection (src/config.py, line 42).
- **RPC keepalive**: `web3.py` `HTTPProvider` by default creates a new `requests.Session` per call unless `request_kwargs={"session": shared_session}` is passed. Competitors patch this.
- **Batch JSON-RPC**: for balance/allowance checks, competitors batch multiple `eth_call` into a single `batch_request` rather than sequential calls.

---

## Section 2: API Best Practices

### 2.1 Current State in CascadeFade

Our `CMCClient` (src/cmc_client.py) has several sub-optimal patterns:

| Aspect | Current | Best Practice |
|--------|---------|---------------|
| **Session lifecycle** | Lazy-created on first `_get_session()`, recreated if `session.closed` | Create once in `__init__` (or `setup()`), reuse forever |
| **Connector config** | Default `aiohttp.ClientSession()` (implicit connector) | Explicit `TCPConnector(limit=100, limit_per_host=30, enable_cleanup_closed=True, force_close=False)` |
| **Keep-alive** | Default (aiohttp does keepalive, but no explicit control) | Set `headers["Connection"]: "keep-alive"`; use ` TCPConnector(keepalive_timeout=30)` |
| **Gzip** | Not explicitly enabled | CMC supports gzip; add `headers["Accept-Encoding"]: "gzip"` to reduce payload ~60-70% |
| **DNS caching** | aiohttp default (ttl=10s) | `ttl_dns_cache=300` to avoid repeated DNS lookups |
| **SSL session reuse** | Default | `ssl=False` for localhost/dev only; in prod, ensure `ssl_context` is shared |
| **Timeout granularity** | `total=CMC_TIMEOUT` (30s) | Split: `connect=10`, `sock_read=20` so hung DNS doesn't eat full 30s |
| **Rate-limit semaphore** | `asyncio.Semaphore(5)` — coarse | Per-endpoint bucketing; CMC has tiered limits (e.g., 10k/mo on trial, 30/min on basic). Use token-bucket or `aiolimiter` |
| **Batching** | Single bulk call per cycle | Good. But CMC has a hard limit of ~100 symbols per call. We have 50, so fine. However, if held + basket grows >100, we need chunking. |

### 2.2 CMC API-Specific Optimizations

1. **Symbol vs ID lookup**: CMC's `quotes/latest` endpoint prefers numeric IDs for stability. Our code falls back to symbols (src/cmc_client.py, lines 80-86). Competitors maintain a warm `symbol→id` cache and use IDs exclusively after first resolution.

2. **Response compression**: CMC Pro API supports gzip. Adding `Accept-Encoding: gzip` can reduce a 50-symbol response from ~25KB to ~8KB.

3. **Error handling for 429**: Our retry logic sleeps on `Retry-After` header (src/cmc_client.py, lines 58-60), but doesn't freeze the whole session. Good. Could be improved with circuit-breaker pattern after N consecutive 429s.

4. **Trial vs Pro endpoint**: We have `CMC_TRIAL_URL` defined but never used (src/config.py, line 30). Competitors auto-fallback from Pro to Trial on 402/403 to preserve uptime.

### 2.3 Web3 / BSC RPC Best Practices

| Aspect | Current | Best Practice |
|--------|---------|---------------|
| **Provider** | `Web3.HTTPProvider(BSC_RPC_URL)` | Use `AsyncHTTPProvider` with `aiohttp` session for non-blocking RPC |
| **Session reuse** | Default `requests` per call | Pass `request_kwargs={"session": shared_aiohttp_session}` |
| **Connection pool** | None | `request_kwargs={"pool_connections": 20, "pool_maxsize": 20}` |
| **Batch requests** | Sequential `eth_call` in `estimate_slippage_single` | Use `web3.BatchRequest` or `eth_call` multicall (e.g., `Multicall3` contract at `0xcA11bde05977b3631167028862bE2a173976CA11`) |
| **Block subscription** | Polling `w3.eth.block_number` in setup only | Use `eth_subscribe` via WebSocket for real-time block/gas price updates |

---

## Section 3: Async Best Practices

### 3.1 Event Loop Health

#### Current Issues in CascadeFade

1. **Synchronous Web3 calls in async context**: `Quoter.estimate_slippage_single()` (src/quoter.py, line 78) calls `self.quoter.functions.quoteExactInputSingle(params).call()` — this is a **blocking synchronous network call** inside the asyncio event loop. It will block the entire loop for the duration of the RPC round-trip (~100-500ms). In a 30-minute cycle this is tolerable, but under load or with multiple fee-tier iterations it serializes latency.

2. **Subprocess TWAK without thread pool**: `TWAKExecutor._run()` (src/twak.py, line 42) uses `asyncio.create_subprocess_exec`, which is async-friendly, but `proc.communicate()` can buffer large outputs. The timeout is 120s, which is very long for a trading bot.

3. **No `asyncio.to_thread` for CPU-bound work**: `DecisionEngine.evaluate()` (src/decision.py) does scoring/math synchronously. With 10 narratives × 5 buckets, this is trivial CPU load, but as scoring complexity grows, it should be offloaded.

4. **Health check logging is noisy**: `Agent.health_check()` (src/agent.py, line 112) logs at INFO every cycle. In paper mode this is fine; in live mode at 30s intervals it's excessive.

### 3.2 Production Patterns

| Pattern | Implementation | Where to Apply in CascadeFade |
|---------|---------------|------------------------------|
| `loop.run_in_executor()` / `asyncio.to_thread()` | Wrap `w3.eth.call()` and scoring logic | `Quoter.estimate_slippage_single()` scoring loops |
| `asyncio.gather(*coros, return_exceptions=True)` | Concurrent external I/O | Currently missing — we could parallelize CMC + FearGreed + DEXTrending |
| `asyncio.wait_for(coro, timeout=5)` | Per-call timeout | Apply to all CMC and RPC calls |
| `asyncio.Lock` for nonce management | Already have `_nonce_lock` in TWAK (src/twak.py, line 20) | Good — keep this |
| `asyncio.Semaphore` for API rate limits | Already have `_semaphore=5` in CMCClient | Good — but make it token-bucket aware |
| Event loop monitoring | Log loop lag: `time.monotonic() - expected_tick_time` | Add to `Agent.health_check()` |
| **Dedicated I/O thread pool** | `concurrent.futures.ThreadPoolExecutor(max_workers=4)` for all sync Web3 calls | Wrap every `web3.py` blocking call |

### 3.3 Decision Engine Async Design

Competitors separate the pipeline into three strictly bounded queues:

```
Market Data (async I/O) → Signal Queue → Decision Queue → Execution Queue
```

Our design mixes I/O and decision logic:
- `SignalEngineClass.evaluate()` calls CMC inside itself (src/signal.py, line 203)
- `DecisionEngine.evaluate()` calls TWAK swaps directly inside the loop (src/decision.py, lines 192, 240)

**Better pattern**: Produce a `SignalEvent` dataclass, then the decision engine consumes it. Execution should be handled by a separate `ExecutionEngine` that subscribes to `ActionEvent`s. This prevents a slow swap from stalling signal generation.

---

## Section 4: SQLite Best Practices

### 4.1 Current State in CascadeFade

Our SQLite usage (src/cache.py, src/portfolio.py, src/log.py) has both good and problematic patterns:

| Aspect | Current | Assessment |
|--------|---------|------------|
| **WAL mode** | `PRAGMA journal_mode=WAL` in all modules | ✅ Good — enables concurrent readers |
| **Synchronous** | `PRAGMA synchronous=NORMAL` | ✅ Good balance of safety and speed |
| **Cache size** | `PRAGMA cache_size=10000` (10K pages ≈ 40MB) | ✅ Good for in-memory hot data |
| **Temp store** | `PRAGMA temp_store=MEMORY` | ✅ Good for temp tables/sorts |
| **Foreign keys** | `PRAGMA foreign_keys=ON` | ✅ Good for referential integrity |
| **Busy timeout** | **MISSING** | ❌ Critical gap — concurrent writes will hit `SQLITE_BUSY` |
| **Shared connection** | Each module creates its own connection | ❌ Sub-optimal — connection per module means multiple WAL files and more fd overhead |
| **BEGIN IMMEDIATE** | Used only in `TradeLogger.log_trade()` | ⚠️ Good start, but missing elsewhere |
| **Transactions per write** | Most methods do `await db.execute(...); await db.commit()` individually | ⚠️ Fine at low frequency, but batching would be better |
| **Index usage** | Indexes on `trades.ts`, `trades.symbol`, `positions.symbol`, `portfolio_snapshots.ts` | ✅ Good |

### 4.2 SQLite Production Best Practices

1. **`PRAGMA busy_timeout = 5000`**: Set a 5-second busy timeout so writers wait instead of immediately failing with `SQLITE_BUSY`. In our codebase, three modules (Cache, Portfolio, TradeLogger) can write concurrently.

2. **Connection pooling with `aiosqlite`**: Instead of each module managing its own connection, use a shared `aiosqlite.Connection` or a simple pool (e.g., `asyncqlite` or a custom wrapper). SQLite allows multiple readers but only one writer at a time even in WAL mode.

3. **Batch inserts**: `Portfolio.compute_value()` (src/portfolio.py, line 228) does one `INSERT` per cycle. This is fine, but if we snapshot every minute, batching 60 inserts into one transaction reduces WAL churn.

4. **Read replicas / second DB**: For heavy analytics, competitors write to a second SQLite file (or parquet/duckdb) and keep the primary DB lean for the hot path.

5. **`PRAGMA mmap_size = 30000000000`**: Memory-map the DB file for faster reads (up to 30GB). Very effective on Linux.

6. **`PRAGMA optimize` / `PRAGMA analysis_limit=400`**: Run `PRAGMA optimize` periodically so SQLite builds better query plans.

7. **Avoid `SELECT MAX(total_value)` on every snapshot**: `Portfolio.compute_value()` (src/portfolio.py, line 221-226) runs `SELECT MAX(total_value) FROM portfolio_snapshots`. This is an O(n) table scan without an index on `total_value`. Add `CREATE INDEX IF NOT EXISTS idx_portfolio_total ON portfolio_snapshots(total_value)` or keep `peak_value` in-memory and only persist periodically.

---

## Section 5: Specific Recommendations for CascadeFade

### 5.1 High Priority (Fix This Week)

| # | Issue | Location | Recommended Fix |
|---|-------|----------|-----------------|
| 1 | **Blocking Web3 calls in event loop** | src/quoter.py:78 | Wrap `self.quoter.functions.quoteExactInputSingle(params).call()` in `await asyncio.to_thread(...)` or use `AsyncHTTPProvider` |
| 2 | **Missing `busy_timeout`** | src/cache.py:37, src/portfolio.py:51, src/log.py:24 | Add `PRAGMA busy_timeout = 5000` immediately after WAL setup |
| 3 | **Session not pre-created / no connector tuning** | src/cmc_client.py:33-40 | Move session creation to `setup()`; add explicit `TCPConnector(limit=100, limit_per_host=30, ttl_dns_cache=300, keepalive_timeout=30, enable_cleanup_closed=True)` |
| 4 | **No gzip on CMC** | src/cmc_client.py:33-40 | Add `headers["Accept-Encoding"] = "gzip"` |
| 5 | **No connection pre-warm** | src/cmc_client.py | Add `await session.get(CMC_BASE_URL)` in `setup()` to establish TCP/TLS before first real request |
| 6 | **Peak value query is unindexed** | src/portfolio.py:221 | Add `CREATE INDEX IF NOT EXISTS idx_portfolio_total ON portfolio_snapshots(total_value)` OR cache peak in-memory |
| 7 | **TWAK swap timeout too long** | src/twak.py:42 | Reduce from 120s to 30s for swaps; 60s for portfolio queries |

### 5.2 Medium Priority (Fix Before Live)

| # | Issue | Location | Recommended Fix |
|---|-------|----------|-----------------|
| 8 | **CMC trial endpoint fallback** | src/config.py:30 | In `CMCClient._request()`, catch 402/403 and retry against `CMC_TRIAL_URL` |
| 9 | **Parallelize independent I/O** | src/agent.py:136-149 | Use `asyncio.gather(cmc.get_bulk_quotes(...), cmc.get_fear_greed(), cmc.get_dex_trending(), return_exceptions=True)` |
| 10 | **Shared DB connection pool** | src/cache.py, src/portfolio.py, src/log.py | Create a single `DBManager` class that holds one `aiosqlite.Connection`; inject into all components |
| 11 | **Add event loop lag monitoring** | src/agent.py:112 | Compute `loop_time = time.monotonic(); lag = loop_time - expected_tick;` log if `lag > interval * 0.1` |
| 12 | **Separate execution from decision** | src/decision.py:192,240 | Move all `self.twak.swap()` calls into an `ExecutionEngine` with an `asyncio.Queue` so slow swaps don't stall the decision loop |
| 13 | **Add circuit breaker for CMC** | src/cmc_client.py | After 3 consecutive failures, enter "degraded mode" for 60s where decisions use last-known prices |
| 14 | **Batch JSON-RPC for slippage** | src/quoter.py:78 | Use `Multicall3` contract on BSC (`0xcA11bde05977b3631167028862bE2a173976CA11`) to query all 4 fee tiers in one `eth_call` |
| 15 | **Symbol→CMC ID cache** | src/cmc_client.py:80-86 | On first bulk fetch, populate `CMC_SYMBOL_TO_ID` and persist to SQLite. Subsequent fetches use `id=` exclusively |

### 5.3 Low Priority (Nice to Have)

| # | Issue | Location | Recommended Fix |
|---|-------|----------|-----------------|
| 16 | **HTTP/2 for CMC** | src/cmc_client.py | Evaluate `httpx` with `http2=True`; aiohttp does not support HTTP/2 client natively |
| 17 | **WebSocket RPC for blocks** | src/quoter.py | Add `w3_ws` provider for `eth_subscribe('newHeads')` to get gas/baseFee updates in real time |
| 18 | **DuckDB for analytics** | src/portfolio.py | Mirror `trades` and `portfolio_snapshots` to DuckDB for fast analytical queries without impacting SQLite hot path |
| 19 | **aiohttp vs httpx benchmark** | src/cmc_client.py | Run a local benchmark: same 50-symbol payload with aiohttp (default) vs aiohttp (tuned) vs httpx (HTTP/1.1) vs httpx (HTTP/2) |
| 20 | **Mempool protection** | src/config.py:42 | Evaluate BloXroute BSC endpoints or Flashbots-style bundles for `eth_sendPrivateTransaction` |

### 5.4 Architecture Diagram — Target State

```
┌─────────────────────────────────────────────────────────────┐
│                    CascadeFade Agent                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Data Feed  │  │   Signal    │  │   Decision Engine   │  │
│  │  Engine     │──│   Engine    │──│   (read-only)       │  │
│  │             │  │  (scoring)  │  │                     │  │
│  │ • CMCClient │  │             │  │                     │  │
│  │ • Web3 RPC  │  │             │  │                     │  │
│  │ • TWAK sync │  │             │  │                     │  │
│  └─────────────┘  └─────────────┘  └──────────┬──────────┘  │
│                                                │             │
│                                     ┌──────────▼──────────┐  │
│                                     │   Execution Queue   │  │
│                                     │   (asyncio.Queue)   │  │
│                                     └──────────┬──────────┘  │
│                                                │             │
│                                     ┌──────────▼──────────┐  │
│                                     │  Execution Engine   │  │
│                                     │  • TWAK swaps       │  │
│                                     │  • Nonce mgmt       │  │
│                                     │  • Tx confirmation  │  │
│                                     └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │   Shared SQLite     │
              │   (WAL + busy_timeout│
              │    + single conn)   │
              └─────────────────────┘
```

---

## Citations

| Source | File/URL | Lines / Description |
|--------|----------|---------------------|
| CascadeFade source | `src/agent.py` | Main loop, health check, cycle orchestration |
| CascadeFade source | `src/cmc_client.py` | CMC API client, session management, retries |
| CascadeFade source | `src/signal.py` | Regime detection, 5-bucket scoring, signal engine |
| CascadeFade source | `src/decision.py` | Position sizing, buy/sell logic, TWAK execution |
| CascadeFade source | `src/config.py` | Constants, allowlist, narrative baskets |
| CascadeFade source | `src/cache.py` | SQLite cache with WAL, no busy_timeout |
| CascadeFade source | `src/portfolio.py` | Position tracking, snapshots, peak value query |
| CascadeFade source | `src/quoter.py` | Blocking Web3 `eth_call` in event loop |
| CascadeFade source | `src/twak.py` | TWAK CLI wrapper, subprocess execution |
| CascadeFade source | `src/risk.py` | Risk guards, drawdown, heartbeat |
| CascadeFade source | `src/log.py` | Trade journal, `BEGIN IMMEDIATE` used selectively |
| Competitor pattern | `asbestos22/narrative-rotation-index` (referenced) | Cited in src/config.py line 83 as source for NARRATIVE_BASKETS |
| aiohttp docs | https://docs.aiohttp.org/en/stable/client_advanced.html | TCPConnector tuning, keepalive, DNS cache |
| SQLite WAL mode | https://www.sqlite.org/wal.html | Concurrent read/write behavior |
| web3.py AsyncHTTPProvider | https://web3py.readthedocs.io/en/stable/providers.html | Non-blocking RPC calls |
| Multicall3 BSC | `0xcA11bde05977b3631167028862bE2a173976CA11` | Standard multicall contract for batching `eth_call` |
| Hummingbot architecture | GitHub: `hummingbot/hummingbot` | Shared aiohttp session pool, connector abstraction |
| Freqtrade architecture | GitHub: `freqtrade/freqtrade` | Async exchange client, rate-limiting with `ccxt.async_support` |

---

*Report generated by research sub-agent for Phase 2 performance optimization.*
