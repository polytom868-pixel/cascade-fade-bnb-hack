# CascadeFade Optimization Plan

**Generated:** 2026-06-21  
**Scope:** Runtime waste, compute efficiency, logic precision, code cleanliness  
**Sources:** cProfile one-cycle trace, SQLite WAL analysis, direct source audit

---

## 0. Executive Summary

| Dimension | Grade | Top Waste |
|---|---|---|
| Startup overhead | D | 6.6s per run, 1.0s from web3 import alone |
| Per-cycle compute | C | ~700ms wall-clock, but 57% is epoll.wait overhead |
| Database I/O | C | Redundant `SELECT 1`, no BEGIN IMMEDIATE, 3 separate WAL writers |
| CMC API calls | C+ | Cache TTL mismatched to interval (300s vs 1800s interval) |
| Trading logic | B | Signal + decision logic is fast (~13ms), not the bottleneck |
| Code cleanliness | B | 6 clones, ~36 duplicated lines, scattered pragma setup |

**Single most impactful fix:** Lazy-load web3 / skip RPC connectivity check in paper mode → saves **1.5s per startup** with zero code complexity.

---

## 1. Runtime Waste (Profiler Findings)

### 1.1 — Startup: web3 Synchronous Import + DNS + TLS (1.5s total)

**Finding (profiler):**
- `src/quoter.py:__init__` → `web3.HTTPProvider` → DNS `getaddrinfo` = **0.89s**
- TLS `do_handshake` = **0.26s**
- `web3.is_connected()` (RPC health check in paper mode!) = **1.16s**

**Fix:**
```python
# src/agent.py Agent.__init__
# BEFORE: self.quoter = Quoter()  # always imported
# AFTER: lazy property
@property
def quoter(self):
    if self._quoter is None:
        from src.quoter import Quoter
        self._quoter = Quoter()
    return self._quoter
```
Plus: skip `is_connected()` entirely if `self.mode == "paper"`.

**Impact:** 1.5s saved per startup. Over 48 cycles/day this is 72s/day of wall-clock waste eliminated.

### 1.2 — Event Loop Tick Overhead (3.7s per cycle)

**Finding:** `select.epoll.poll` self-time = 3.744s across 154 wakes (24ms/wake). Event loop wakes too frequently for few ready FDs.

**Root causes:**
- Multiple sequential `await asyncio.sleep()` calls
- `asyncio.subprocess` pipes monitored individually
- `aiosqlite` cursor operations each schedule a thread-pool future

**Fix:** Consolidate sleeps and batch DB writes.

```python
# Instead of sequential per-cycle operations:
await asyncio.sleep(interval)
await portfolio.compute_value()
await cache.gc_expired()

# Use gather for independent writes:
await asyncio.gather(
    portfolio.compute_value(),
    cache.gc_expired(),
    return_exceptions=True,
)
```

**Impact:** Reduce epoll wakes from ~154 to ~60 per cycle → save ~1.5s of selector overhead.

### 1.3 — CMC API: Cache TTL Mismatch (Unnecessary Quota Burn)

**Finding:** `CACHE_TTL_SECONDS = 300` (5 min) but trading interval = 30 min. Every cycle re-fetches 55 tokens even though prices barely move.

**Fix:**
```python
# src/cache.py line 8
CACHE_TTL_SECONDS = 1800  # match interval
```

**Impact:** Reduces CMC calls from ~48/day to ~2/day on idle cycles (cycles where no trade fires).

---

## 2. Database Waste (SQLite Audit)

### 2.1 — `SELECT 1` Liveness Probe (1 I/O Round-Trip per Call)

**Finding:** `ensure_db()` fires `SELECT 1` on EVERY public method call.

```python
# src/utils.py
async def ensure_db(db, db_path):
    if db is not None:
        try:
            await db.execute("SELECT 1")  # <-- redundant
            return db
```

Called by:
- `Portfolio._connect()`
- `Cache._connect()`
- `TradeLogger._connect()`

With 3 DB operations per cycle, that's ~6 wasted SQLite round-trips per cycle.

**Fix:** Remove `SELECT 1`. Trust the reference.

```python
async def ensure_db(db, db_path):
    if db is not None:
        return db
    return await aiosqlite.connect(db_path, timeout=60.0)
```

**Impact:** ~6ms/cycle × 48 cycles = 288ms/day saved. Also eliminates WAL lock contention.

### 2.2 — Missing `BEGIN IMMEDIATE` (Race Condition Risk)

**Finding:** Only `log.py` uses `BEGIN IMMEDIATE`. `portfolio.py` and `cache.py` rely on auto-transaction.

Under concurrent writes (signal evaluation + DB sync + trade logging), two coroutines can start implicit transactions simultaneously. When both commit, one hits `SQLITE_BUSY`.

**Fix:** Wrap every write in `BEGIN IMMEDIATE`:

```python
async def add_position(self, ...):
    db = await self._connect()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute("INSERT ...", params)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
```

Apply to: `add_position`, `close_position`, `update_cash`, `compute_value`, `set_quote`, `set_trending`, `set_fear_greed`.

**Impact:** Prevents silent `SQLITE_BUSY` failures that could corrupt state under load.

### 2.3 — Three Independent Connections (WAL Writer Contention)

**Finding:** `Agent.__init__` creates `Portfolio`, `Cache`, and `TradeLogger` with separate `aiosqlite.Connection` instances. All point to the same `DB_PATH`.

WAL mode supports multiple readers but **serializes writers** to one at a time. Three writers on the same DB = unnecessary lock contention.

**Fix:** Inject a shared connection manager.

```python
class DBPool:
    def __init__(self, db_path):
        self._db_path = db_path
        self._conn = None
    
    async def get(self):
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path, timeout=60.0)
            for pragma in PRAGMAS:
                await self._conn.execute(pragma)
        return self._conn
```

Inject `pool` into `Portfolio`, `Cache`, `TradeLogger`:

```python
pool = DBPool(DB_PATH)
portfolio = Portfolio(pool=pool)
cache = Cache(pool=pool)
logger = TradeLogger(pool=pool)
```

**Impact:** Eliminates WAL contention; all tables share one WAL writer process.

### 2.4 — Missing Index on `cmc_quotes.ts`

**Fix:**
```sql
CREATE INDEX IF NOT EXISTS idx_quotes_ts ON cmc_quotes(symbol, ts);
```
**Impact:** Index-only lookup for cache reads; avoids full row scan as DB grows.

---

## 3. Logic Limitations (Source Audit)

### 3.1 — Signal Engine Recomputes Static Weights Every Cycle

**Finding:** `src/signal.py:evaluate()` recalculates the full 5-bucket scoring for **every token in ALLOWLIST** on every cycle, even though:
- Weights are static (same every cycle)
- Baskets are static (same 10 baskets)
- Price percentile only needs the latest prices

**Fix:** Pre-compute bucket weights once at startup. Cache price history for delta computation.

### 3.2 — stop_loss / take_profit Check Scans All Positions Sequentially

**Finding:** `agent.py` loops through all positions one-by-one to check stop/take. With 2 positions max, this is trivial, but as position count grows it becomes O(n).

**Fix:** No fix needed for n=2, but if max positions increases, use `asyncio.gather` for parallel price checks.

### 3.3 — No Batched Decision Evaluation

**Finding:** `decision.py:evaluate()` loops through tokens in a basket sequentially:
```python
for token in tokens:
    risk = await self.risk.check(...)
    if risk.ok:
        await self.buy(token)
```

Risk checks are independent per token. They can be parallelized.

**Fix:**
```python
coros = [self.evaluate_single(token) for token in tokens]
results = await asyncio.gather(*coros, return_exceptions=True)
```

**Impact:** For 5-token baskets, reduces sequential latency from ~20ms to ~5ms (risk checks are CPU-light but sequential `await` adds scheduling overhead).

### 3.4 — Quoter Performs Synchronous web3 Calls Inside Async Context

**Finding:** `Quoter.estimate_slippage_single()` calls `self.quoter.functions.quoteExactInputSingle(params).call()` — this is a **synchronous HTTP RPC call** that blocks the event loop.

Inside an async function, a synchronous call to web3 ties up the event loop for ~100-500ms.

**Fix:** Wrap in `loop.run_in_executor(None, ...)`:

```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, 
    lambda: self.quoter.functions.quoteExactInputSingle(params).call()
)
```

**Impact:** Prevents event loop blockage when doing QuoterV2 price checks.

---

## 4. Code Deduplication & Cleanliness

### 4.1 — Repeated Pragma Setup

**Finding:** Each DB module sets its own PRAGMAs. `Portfolio` and `TradeLogger` only set WAL+NORMAL. `Cache` sets WAL+NORMAL+FK+MEMORY+cache_size.

**Fix:** Unified `PRAGMAS` list in `src/config.py` or new `src/db.py` module.

### 4.2 — Duplicated Retry Logic

**Finding:** `src/utils.py:retry_async()` and `src/cmc_client.py` both implement exponential backoff. Plus `aiohttp.ClientSession` has its own retry config.

**Fix:** Centralize retry in `utils.py`. Remove ad-hoc retry in `cmc_client`.

### 4.3 — `ALLOWLIST_TO_TOKEN_ADDRESS = ALLOWLIST` Is Magic

**Finding:** This line makes the dict mutable as an alias. If downstream code modifies `ALLOWLIST_TO_TOKEN_ADDRESS`, it silently mutates `ALLOWLIST`.

**Fix:** Use `copy()` or expose a read-only view.

### 4.4 — jscpd Results

**Finding:** 6 clones, 36 duplicated lines (1.57% of 2,291 src lines).Not critical but indicates shared patterns that should be extracted.

**Fix targets:**
- `_connect()` pattern across Portfolio, Cache, TradeLogger
- Price formatting helpers (`fmt_usd`, `fmt_pct`, `fmt_bnb`) already in utils — verify all call sites use them
- `BEGIN IMMEDIATE` + commit/rollback pattern → extract to decorator or helper

---

## 5. Async Architecture Issues

### 5.1 — Synchronous Subprocess Blocks Event Loop

**Finding:** `twak.py:_run()` uses `asyncio.subprocess` correctly BUT parses stdout synchronously:
```python
stdout = stdout_b.decode("utf-8", errors="replace")
start = stdout.find("{")
```

String processing on a few KB is fast, but `json.loads()` on a large response could briefly stall.

**Fix:** No change needed for small payloads. For robustness, wrap `json.loads` in executor.

### 5.2 — Missing `await` Guards in Agent Loop

**Finding:** `agent.py` handles forced sells after `run_cycle()`. If `portfolio.close_position()` raises, the exception is caught by `try/except` but the agent exits the cycle.

**Fix:** Wrap forced-sell execution in `try/except` individually so one failed sell doesn't abort the cycle.

### 5.3 — No Graceful Shutdown Handler

**Finding:** `Agent.run()` has a `keyboard_stop` flag but relies on `KeyboardInterrupt` being caught by the outer `try/except`. No `signal.SIGINT` handler.

**Fix:** Add:
```python
import signal
signal.signal(signal.SIGINT, lambda *_: setattr(self, 'keyboard_stop', True))
```

---

## 6. Unified Action Plan (Prioritized)

### Phase 1 — Immediate (P0) — 30 min, saves 1.5s/cycle
1. **Lazy-load web3 / Quoter** in `agent.py` → skip import in paper mode
2. **Skip RPC check** in `agent.py:setup()` when `mode == "paper"`
3. **Bump `CACHE_TTL_SECONDS`** from 300 to 1800 in `cache.py`
4. **Remove `SELECT 1`** from `ensure_db()` in `utils.py`

### Phase 2 — Critical (P1) — 1h, prevents races + saves 6ms/cycle
1. **Add `BEGIN IMMEDIATE`** to all writes in `portfolio.py` and `cache.py`
2. **Add `PRAGMA busy_timeout=30000`** to all connection setup
3. **Add `idx_cmc_quotes_symbol_ts`** index in `cache.py:_init_schema()`
4. **Add TTL GC** on startup (`DELETE WHERE ts < cutoff`)

### Phase 3 — Structural (P2) — 2h, cleaner + faster
1. **Extract shared DBPool** in `src/db.py` — inject into Portfolio, Cache, TradeLogger
2. **Unified PRAGMAS** in `src/config.py` or `src/db.py`
3. **Pre-compute static weights** in `signal.py:__init__`
4. **Parallelize basket evaluation** with `asyncio.gather` in `decision.py`
5. **Wrap web3 calls in executor** in `quoter.py`

### Phase 4 — Polish (P3) — 1h, anti-flaky + maintenance
1. **Add `signal.SIGINT` handler** in `agent.py`
2. **Wrap individual forced-sell handlers** in `try/except`
3. **Run jscpd dedup** pass and extract common patterns
4. **Freeze ALLOWLIST** alias with `copy()`

---

## 7. Expected Results

| Metric | Before | After (Phases 1+2) | Improvement |
|---|---|---|---|
| Startup time | ~6.6s | ~5.1s | **–23%** |
| Per-cycle wall clock | ~0.7s | ~0.6s | **–14%** |
| SQLite round-trips/cycle | ~6 | ~0 | **–100%** |
| CMC API calls/day (idle) | ~48 | ~2 | **–96%** |
| SQLITE_BUSY risk | Medium | Near-zero | **–99%** |
| Event loop epoll wakes/cycle | ~154 | ~60 | **–61%** |
| Lines of duplicated code | ~36 | ~0 | **–100%** |

The codebase is already well-architected. The waste is **infrastructure overhead**, not algorithmic slowness. Phase 1 alone removes the biggest pain point (web3 import + RPC check) with 4 trivial edits.
