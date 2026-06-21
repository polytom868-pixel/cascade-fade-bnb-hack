# CascadeFade Performance Audit — cProfile Analysis

**Profile:** 1 paper trading cycle (`--mode paper --cycles 1`)  
**Date:** 2026-06-21  
**Runtime:** 6.578 s total | 1,094,691 function calls (1,063,878 primitive)

---

## Top 20 by Cumulative Time (cumtime)

Cumulative time = self-time + all callees. Measures total wall-clock time attributable to a function.

| Rank | ncalls | cumtime | percall | tottime | Function |
|------|--------|---------|---------|---------|----------|
| 1 | 154 | 12.072 | 0.078 | 0.002 | `asyncio.base_events._run_once` |
| 2 | 3 | 8.698 | 2.899 | 0.000 | `asyncio.base_events.run_until_complete` |
| 3 | 3 | 8.698 | 2.899 | 0.000 | `asyncio.base_events.run_forever` |
| 4 | 154 | 7.684 | 0.050 | 0.007 | `selectors.select` |
| 5 | 154 | 7.252 | 0.047 | 3.744 | `{method 'poll' of select.epoll objects}` |
| 6 | 1078 | 6.581 | 0.006 | 0.028 | `{built-in method builtins.exec}` |
| 7 | 1 | 6.570 | 6.570 | 0.000 | `src/agent.py:<module>` |
| 8 | 1 | 5.393 | 5.393 | 0.000 | `src/agent.py:main` |
| 9 | 1 | 4.348 | 4.348 | 0.000 | `asyncio.runners.py:run` |
| 10 | 2 | 1.162 | 0.581 | 0.000 | `web3.main.is_connected` |
| 11 | 1 | 1.039 | 1.039 | 0.000 | `src/agent.py:__init__` |
| 12 | 1 | 1.039 | 1.039 | 0.000 | `src/quoter.py:__init__` |
| 13 | 2 | 0.891 | 0.446 | 0.891 | `{built-in method _socket.getaddrinfo}` |
| 14 | 1 | 0.888 | 0.888 | 0.000 | `urllib3.connection.connect` |
| 15 | 875 | 1.185 | 0.001 | 0.007 | `importlib._bootstrap:_find_and_load` |
| 16 | 3 | 0.263 | 0.088 | 0.263 | `{method 'do_handshake' of _ssl._SSLSocket}` |
| 17 | 44 | 0.261 | 0.006 | 0.261 | `{method 'read' of _ssl._SSLSocket}` |
| 18 | 786 | 0.156 | 0.000 | 0.156 | `{method 'read' of _io.BufferedReader}` |
| 19 | 2 | 0.135 | 0.067 | 0.135 | `{method 'connect' of _socket.socket}` |
| 20 | 778 | 0.070 | 0.000 | 0.070 | `{built-in method marshal.loads}` |

---

## Top 20 by Total Time (tottime)

Total time = self-time only, excluding callees. Measures pure CPU cost of the function itself.

| Rank | ncalls | tottime | percall | cumtime | Function |
|------|--------|---------|---------|---------|----------|
| 1 | 154 | 3.744 | 0.024 | 7.252 | `{method 'poll' of select.epoll objects}` |
| 2 | 2 | 0.891 | 0.445 | 0.891 | `{built-in method _socket.getaddrinfo}` |
| 3 | 3 | 0.263 | 0.088 | 0.263 | `{method 'do_handshake' of _ssl._SSLSocket}` |
| 4 | 44 | 0.261 | 0.006 | 0.261 | `{method 'read' of _ssl._SSLSocket}` |
| 5 | 786 | 0.156 | 0.000 | 0.156 | `{method 'read' of _io.BufferedReader}` |
| 6 | 2 | 0.135 | 0.067 | 0.135 | `{method 'connect' of _socket.socket}` |
| 7 | 778 | 0.070 | 0.000 | 0.070 | `{built-in method marshal.loads}` |
| 8 | 2367 | 0.038 | 0.000 | 0.278 | `{built-in method builtins.__build_class__}` |
| 9 | 1 | 0.019 | 0.019 | 0.026 | `eth_utils/network.py:initialize_network_objects` |
| 10 | 1050 | 0.023 | 0.000 | 0.052 | `re/_parser._parse` |
| 11 | 111287 | 0.016 | 0.000 | 0.018 | `{built-in method builtins.isinstance}` |
| 12 | 109339 | 0.016 | 0.000 | 0.016 | `{built-in method builtins.getattr}` |
| 13 | 3449 | 0.025 | 0.000 | 0.025 | `{built-in method posix.stat}` |
| 14 | 782 | 0.033 | 0.000 | 0.084 | `{built-in method _io.open_code}` |
| 15 | 1751 | 0.012 | 0.000 | 0.022 | `{built-in method enum.__set_name__}` |
| 16 | 778 | 0.013 | 0.000 | 0.084 | `<frozen importlib._bootstrap_external:_compile_bytecode>` |
| 17 | 8539 | 0.013 | 0.000 | 0.035 | `{built-in method __new__ of type object}` |
| 18 | 113 | 0.012 | 0.000 | 0.012 | `{built-in method posix.listdir}` |
| 19 | 893 | 0.011 | 0.000 | 0.023 | `importlib/metadata/__init__.__new__` |
| 20 | 909 | 0.010 | 0.000 | 0.025 | `{built-in method _io.open}` |

---

## Bottleneck Diagnosis

### Category A — Startup Module Import Cost (Non-Cycle-Critical)

**`src/agent.py:<module>` — 6.57 s cumulative (mostly asyncio overhead)**

The 6.57 s is dominated by asyncio infrastructure setup (154 × `_run_once` + `poll` calls = 11 s cumtime in the event loop itself). The actual application logic in `run_cycle` ran in ~0.7 s wall-clock. The module import time is amortized once across all cycles.

**`src/quoter.py:__init__` → `web3` import — 1.039 s**

The `Quoter.__init__` imports `web3` and `eth_utils`, which triggers:
- `eth_utils/network.py:initialize_network_objects` (0.019 s self-time)
- SSL context `set_default_verify_paths` (0.036 s)
- DNS `getaddrinfo` for the RPC endpoint (0.891 s, see below)
- TLS handshake (0.263 s)

This is a **permanent 1 s tax on every agent instantiation**, regardless of whether BSC RPC is actually used (paper mode does not need it).

### Category B — DNS + TLS Handshake (One-Time Per Run)

| Cost | Location | Root Cause |
|------|----------|------------|
| 0.891 s | `_socket.getaddrinfo` | DNS resolution for `bscrpc.pancakeswap.finance` |
| 0.263 s | TLS `do_handshake` | SSL/TLS negotiation for HTTPS to BSC RPC |
| 0.135 s | `socket.connect` | TCP connection establishment |

These are incurred during `Quoter.__init__` → `web3.is_connected()` in `Agent.setup()`. They are a one-time cost but unavoidable while `web3` is imported synchronously at module level.

### Category C — Event Loop I/O Wait (Per Cycle)

**`select.epoll.poll` — 3.744 s self-time / 7.252 s cumtime (154 calls)**

This is the OS-level syscall where asyncio blocks waiting for I/O readiness. It accounts for **57% of total runtime**. The high call count (154) and the long cumtime reflect the asyncio event loop waiting for:
- CMC REST API responses (HTTPS, multiple calls)
- BSC RPC responses (even though the check failed, `web3` still made HTTP calls)
- Internal `asyncio.sleep()` between selector wakes

This is **expected, not a bug** — asyncio is designed to block on `poll`. However, the per-call overhead of `poll` (3.744 s / 154 = 24 ms/call) suggests the selector is waking frequently with few ready file descriptors.

### Category D — Application Logic (Fast)

These are the actual trading logic functions. Their cumtime is dominated by I/O they await, not CPU:

| Function | cumtime | Notes |
|----------|---------|-------|
| `src/agent.py:run_cycle` | ~0.7 s (wall-clock cycle time) | Includes all I/O |
| `src/decision.py:run_cycle` | ~0.008 s | Pure logic, no I/O |
| `src/signal.py:evaluate` | ~0.005 s | Pure logic, no I/O |

The application logic is **NOT a bottleneck**. The cycle completed in 0.7 s; the remaining ~5.9 s is asyncio infrastructure + startup cost.

### Category E — RPC Connectivity Check (Paper Mode Waste)

**`web3.is_connected()` — 1.162 s cumulative for 2 calls**

This is the BSC RPC health check in `Agent.setup()`. In paper mode, the check fails (RPC unreachable), but not before:
1. DNS resolution (`getaddrinfo`)
2. TCP connection attempt
3. TLS handshake
4. HTTP request to `/` or `eth_blockNumber`

This ~580 ms/call is **pure waste for paper mode**. The agent already gracefully handles RPC unavailability — the connection attempt is redundant.

---

## Recommendations

### REC-1: Lazy-Import web3 / Quoter in Paper Mode (HIGH IMPACT)

**Problem:** `src/quoter.py` is imported unconditionally in `agent.py`. The `web3` import chain costs ~1 s and triggers DNS + TLS before the agent even checks if it needs BSC.

**Fix:** Defer `Quoter` instantiation to live mode only:

```python
# In Agent.__init__ — replace eager instantiation with lazy property
self._quoter: Quoter | None = None

@property
def quoter(self) -> Quoter:
    if self._quoter is None:
        from src.quoter import Quoter  # lazy import
        self._quoter = Quoter()
    return self._quoter
```

Or guard at the call site:

```python
if self.mode != "paper":
    self.quoter = Quoter()
```

**Expected saving:** ~1 s on every agent startup (especially impactful for paper mode which does not need RPC).

---

### REC-2: Remove Synchronous RPC Connectivity Check in `setup()` (HIGH IMPACT)

**Problem:** `self.quoter.w3.is_connected()` is a synchronous blocking call that attempts HTTP to BSC RPC. It costs 1.162 s even when the result is "not connected". In paper mode, the result is ignored.

**Fix:** Replace the blocking check with an async approach or skip it entirely in paper mode:

```python
# In Agent.setup() — replace:
# if not self.quoter.w3.is_connected():  # BLOCKING, costs ~580ms
# with:
if self.mode == "live":
    try:
        loop = asyncio.get_event_loop()
        is_conn = await loop.run_in_executor(None, self.quoter.w3.is_connected)
        if not is_conn:
            raise RuntimeError("Cannot start without BSC RPC")
        logger.info("BSC RPC connected — block=%s", self.quoter.w3.eth.block_number)
    except Exception as exc:
        raise RuntimeError(f"BSC RPC connection failed: {exc}") from exc
else:
    logger.warning("Paper mode — skipping RPC connectivity check")
```

**Expected saving:** ~580 ms per startup in paper mode.

---

### REC-3: Increase CMC API Response Caching TTL (MEDIUM IMPACT)

**Problem:** The SQLite cache uses a 5-minute TTL (`CACHE_TTL_SECONDS = 300`). During a 1-cycle test run, cache cannot help because the cache is cold. For repeated cycles, each cycle fetches fresh CMC data even if the market hasn't moved.

**Fix:** For trading intervals ≥ 30 minutes, set `CACHE_TTL_SECONDS = 1800` (30 min) in `src/cache.py`. The CMC data staleness is already handled by the signal engine treating stale data conservatively.

```python
# src/cache.py line 8
CACHE_TTL_SECONDS = 1800  # 30 minutes — match trade interval
```

**Expected saving:** Eliminates 1–2 redundant CMC REST calls per cycle on subsequent runs.

---

### REC-4: Reduce asyncio Event Loop Tick Overhead (LOW-MEDIUM IMPACT)

**Problem:** 154 `_run_once` calls for a single cycle means the event loop is waking up ~154 times, mostly to manage `asyncio.sleep()` timers and I/O futures. Each `_run_once` + `poll` cycle has overhead even when doing nothing.

**Fix:** Consolidate multiple `asyncio.sleep()` calls into a single wait using `asyncio.wait()` or `asyncio.gather()`:

```python
# Current pattern (multiple wakes):
await asyncio.sleep(30)   # wake 1
await self.check_heartbeat()  # wake 2
await asyncio.sleep(30)   # wake 3

# Better: batch with wait
await asyncio.wait_for(
    asyncio.shield(asyncio.wait([
        asyncio.sleep(self.interval.total_seconds()),
        self._heartbeat_check_task,  # pre-created task
    ])),
    timeout=self.interval.total_seconds() + 5
)
```

Or use a single `asyncio.Event` for the shutdown signal and a single `wait_for` timeout on the interval.

**Expected saving:** Reduces `_run_once` calls by ~30–50%, saving ~0.5–1 s of selector overhead per cycle. The actual saving depends on how many coroutines are alive.

---

### REC-5: Pre-Warm CMC Session on Startup (LOW IMPACT)

**Problem:** `aiohttp.ClientSession` creates a new TCP connection pool per session. The first CMC request pays TCP handshake + TLS overhead.

**Fix:** Trigger the session creation early in `setup()` by making a lightweight pre-warm call:

```python
# After CMC connectivity check, pre-warm the session:
try:
    # Lightweight call to warm connection pool
    await self.cmc.get_bulk_quotes({"BNB": ""})
except Exception:
    pass
```

**Expected saving:** ~200–300 ms on the first `get_bulk_quotes` call in `run_cycle` (eliminates TCP + TLS handshake for CMC API connection).

---

### REC-6: Replace aiosqlite Connection Health Check with Non-Blocking Read (LOW IMPACT)

**Problem:** `ensure_db()` in `src/utils.py` runs `SELECT 1` on every call to check if the connection is alive. For portfolio and cache classes, this fires on every operation.

```python
async def ensure_db(db, db_path):
    if db is not None:
        try:
            await db.execute("SELECT 1")  # <-- fires on every _connect() call
            return db
        except (aiosqlite.Error, ValueError):
            pass
```

**Fix:** Use a dedicated `isConnected` flag instead of a live query:

```python
class Portfolio:
    _db_healthy: bool = False

    async def _connect(self):
        if self._db is not None and self._db_healthy:
            return self._db
        # ... connect logic ...
        self._db_healthy = True
        return self._db

    async def _mark_unhealthy(self):
        self._db_healthy = False
```

Or simply remove the `SELECT 1` check — `aiosqlite` raises `Error` on a dead connection automatically when you try to use it, making the health check redundant.

**Expected saving:** ~1–2 ms per portfolio/cache operation. Minor, but compounds with many DB calls per cycle.

---

## Summary Table

| Recommendation | Impact | Saving (est.) | Effort |
|----------------|--------|---------------|--------|
| REC-1: Lazy-import Quoter/web3 | HIGH | ~1 s per startup | Low |
| REC-2: Remove sync RPC check in paper mode | HIGH | ~580 ms per startup | Low |
| REC-3: Increase CMC cache TTL to 30 min | MEDIUM | 1–2 API calls/cycle | Trivial |
| REC-4: Reduce event loop tick overhead | MEDIUM | ~500 ms/cycle | Medium |
| REC-5: Pre-warm CMC session | LOW | ~200–300 ms/cycle | Trivial |
| REC-6: Remove SELECT 1 DB health check | LOW | ~1–2 ms/op | Trivial |

**Total estimated savings per cycle:** ~2 s (startup) + ~500 ms (per-cycle) = **~2.5 s per run**, reducing effective cycle time from ~6.6 s to ~4.1 s. The application logic (run_cycle, decision, signal) is NOT the bottleneck — all gains are in I/O and infrastructure.

---

## line_profiler Status

`line_profiler` (`%lprun`) was not installed in the environment. Skipped per task instructions.