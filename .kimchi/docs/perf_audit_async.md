# CascadeFade — Async Architecture Audit

**Date:** 2026-06-21
**Files reviewed:** `src/agent.py`, `src/cmc_client.py`, `src/portfolio.py`, `src/twak.py`, `src/quoter.py`, `src/decision.py`, `src/risk.py`, `src/signal.py`, `src/cache.py`, `src/log.py`, `src/utils.py`

---

## 1. Blocking Calls Found

### CRITICAL — Synchronous web3.py RPC calls blocking the event loop

| File | Line | Severity | Description | Fix |
|------|------|----------|-------------|-----|
| `src/quoter.py` | 89–113 | **CRITICAL** | `estimate_slippage_single()` runs a loop over 4 fee tiers. Each iteration calls `self.quoter.functions.quoteExactInputSingle(params).call()` — a **synchronous HTTP RPC call** via `Web3.HTTPProvider`. This blocks the entire asyncio event loop for the duration of each RPC round-trip (typically 200–1000ms per call, 800ms–4s total for 4 tiers). | Wrap in `asyncio.to_thread()` so the blocking calls run in a thread pool. |
| `src/quoter.py` | 115–137 | **HIGH** | `get_balance()` calls `self.w3.eth.get_balance()` and `token.functions.balanceOf(...).call()` — both synchronous web3 calls blocking the event loop. | Wrap in `asyncio.to_thread()`. |

### HIGH — Synchronous logging from async context

| File | Line | Severity | Description | Fix |
|------|------|----------|-------------|-----|
| `src/log.py` | 117–130 | **HIGH** | `log_trade()` is a module-level synchronous function. It is called from `decision.py:evaluate()` (an `async` function) at line ~140+ via `log_trade("SELL", ...)`. This blocks the event loop during I/O. | Make `log_trade()` async (`async def log_trade()`) and `await` it from callers, or queue logs via `asyncio.create_task()` for fire-and-forget background logging. |

### LOW — Signal handler uses synchronous logging API

| File | Line | Severity | Description | Fix |
|------|------|----------|-------------|-----|
| `src/agent.py` | 46 | **LOW** | `_signal_handler()` calls `logger.warning()` (synchronous logging). While logging itself is rarely blocking, it uses the stdlib logging module which can acquire locks. Minor concern in signal context. | Acceptable as-is. Signal handlers should be minimal. |

---

## 2. Parallelization Opportunities

### OPPORTUNITY 1 — Forced sell execution is sequential (agent.py)

**File:** `src/agent.py:155–165`

```python
for sell in forced_sells:
    sym = sell["token"]
    # ... sequential await of twak.swap() per position
    await self.portfolio.close_position(sym, price, tx_hash)
```

Each sell swap is awaited sequentially. If there are 2 forced sells, the second waits for the first to complete. These could run in parallel with `asyncio.gather()`:

```python
tasks = [
    _exec_forced_sell(sell) for sell in forced_sells
]
await asyncio.gather(*tasks)
```

### OPPORTUNITY 2 — TWAK swap execution in decision.py SELL loop is sequential

**File:** `src/decision.py:evaluate()` — SELL loop (~line 80–110)

The sell loop iterates over positions and awaits `self.twak.swap()` sequentially. In live mode with 2 positions, the second swap waits for the first. Use `asyncio.gather()` or `asyncio.create_task()` to execute all swaps concurrently, then await them with error collection.

### OPPORTUNITY 3 — TWAK swap execution in decision.py BUY loop is sequential

**File:** `src/decision.py:evaluate()` — BUY loop (~line 135–170)

Same pattern as above. Multiple `await self.twak.swap()` calls in a `for` loop execute sequentially. When buying across a basket of tokens, these can be parallelized.

### OPPORTUNITY 4 — Quoter fee tier loop calls are sequential

**File:** `src/quoter.py:95–113`

The 4 QuoterV2 fee tier calls (`quoteExactInputSingle` for each tier) are called sequentially in a `for` loop. These are independent RPC calls and could be parallelized via `asyncio.gather()`:

```python
async def estimate_slippage_single_async(self, ...):
    async def _quote_tier(fee):
        return await asyncio.to_thread(
            self.quoter.functions.quoteExactInputSingle(...).call
        )
    results = await asyncio.gather(*[_quote_tier(fee) for fee in PCS_FEE_TIERS])
```

Note: `asyncio.to_thread()` is preferred here because the underlying web3 calls are synchronous (not coroutines).

### OPPORTUNITY 5 — CMC bulk quote + other fetches in evaluate()

**File:** `src/signal.py:SignalEngineClass.evaluate()` (line ~205)

Currently fetches narrative data in one sequential `await self.cmc.get_bulk_quotes()`. If fear-greed or trending data were also fetched in the same cycle, they should use `asyncio.gather()`. Currently `get_fear_greed()` and `get_dex_trending()` are defined in `cmc_client.py` but not called in the main cycle — this is a future opportunity when the signal engine is fully wired.

### NOT AN ISSUE — Portfolio DB reads are already parallelizable

`portfolio.py` uses `aiosqlite` throughout. Individual methods like `get_positions()`, `get_cash_balance()`, `compute_value()` are async and would compose cleanly with `asyncio.gather()` if called together. No issue here.

---

## 3. Exception Handling Gaps

### MEDIUM — `decision.py:evaluate()` direct dict access without guard

**File:** `src/decision.py:91`

```python
pos = self.portfolio.positions[position_token]  # KeyError if not found
```

Direct key access. If `positions` is modified concurrently (e.g., by another coroutine), this raises `KeyError` unhandled. While the loop uses `list(self.portfolio.positions)`, the direct index access is fragile.

**Fix:** Use `self.portfolio.positions.get(position_token)` with a `continue` guard.

### MEDIUM — `decision.py` SELL path calls `self.portfolio.remove()` without exception handling

**File:** `src/decision.py:113`

```python
self.portfolio.remove(position_token)  # raises KeyError if not found
```

The `remove()` method calls `self.positions.pop(symbol, None)` which is safe (returns None on missing key). However, the subsequent `log_trade()` call (synchronous, see Section 1) could raise, and the `actions["sells"]` append would then be skipped. The try/except around the entire sell block would help.

### MEDIUM — `risk.py:check_heartbeat()` swallows exceptions silently

**File:** `src/risk.py:46–54`

```python
try:
    last = datetime.fromisoformat(last_ts)
    hours_since = (now - last).total_seconds() / 3600
    if hours_since < 22:
        return {"needed": False, ...}
except Exception:
    pass  # silently falls through to heartbeat check
```

Silently ignoring parsing errors means a malformed timestamp always triggers a heartbeat trade. Low severity but could cause unnecessary trades.

### LOW — `quoter.py` catches `Exception` and logs at DEBUG only

**File:** `src/quoter.py:107–110`

```python
except Exception as exc:
    logger.debug("Quoter failed for %s→%s fee=%d: %s", ...)
    continue
```

A failed quote silently returns the "best so far" result with no indication that some tiers failed. If all 4 tiers fail (e.g., no liquidity, RPC error), the function returns `{"amount_out": 0, ...}` with no error field set. Caller (`decision.py`) may not detect the failure.

### LOW — `agent.py:run_cycle()` wraps `run_cycle()` in try/except but does not propagate

**File:** `src/agent.py:129`

```python
try:
    summary = await self.decision.run_cycle(cash, price_map)
except Exception as exc:
    logger.exception("Cycle %d failed: %s", self._cycle_count, exc)
    summary = {"error": str(exc), "actions": {...}}
```

An exception in the decision engine results in an empty action set. This is a safe fallback (agent continues), but the error summary is swallowed — not surfaced to external monitoring. Consider setting a `self._last_error` field or logging at `warning` level for observability.

### OK — `risk.py` methods are intentionally fault-tolerant

Methods like `risk.exposure_check()`, `risk.position_size()`, `risk.pre_trade_check()`, `risk.select_heartbeat_pair()` are synchronous and have no try/except. This is acceptable because:
- They are pure computation with no I/O
- A crash in a risk check should fail-open (return `approved=True`) or the caller handles it

No change needed.

---

## 4. Event Loop Health

### CRITICAL CONCERN — `quoter.py` synchronous web3 blocking calls

The single most serious async health issue is in `src/quoter.py`:

- `estimate_slippage_single()` makes 4 sequential synchronous RPC calls
- `get_balance()` makes 1–2 synchronous RPC calls

During each call, the **entire event loop is blocked**. With a typical BSC RPC latency of 200–500ms:
- 4-tier slippage check: **800ms–2s of event loop starvation**
- Balance check: **200–500ms of event loop starvation**

During this time:
- No other coroutines can run
- The main agent loop cannot respond to shutdown signals
- CMC health checks are blocked
- Portfolio DB writes are blocked

**Recommended fix**: Wrap all web3 synchronous calls in `asyncio.to_thread()`:

```python
async def estimate_slippage_single_async(self, ...):
    def _call():
        return self.quoter.functions.quoteExactInputSingle(params).call()
    result = await asyncio.to_thread(_call)
```

### HEALTHY — `asyncio.wait_for()` used correctly for shutdown

**File:** `src/agent.py:172–180`

```python
while not _shutdown_requested.is_set():
    try:
        await asyncio.wait_for(_shutdown_requested.wait(), timeout=self.interval.total_seconds())
    except asyncio.TimeoutError:
        pass
```

This pattern is correct: the loop sleeps until either the interval expires OR a shutdown signal arrives. No busy-waiting.

### HEALTHY — `asyncio.Semaphore` rate limiting in CMC client

**File:** `src/cmc_client.py:43`

```python
self._semaphore = asyncio.Semaphore(5)
```

Concurrent CMC requests are correctly rate-limited to 5 simultaneous calls.

### HEALTHY — `asyncio.create_subprocess_exec()` for TWAK

**File:** `src/twak.py:49–56`

TWAK uses `asyncio.create_subprocess_exec()` which is the correct async primitive for subprocess I/O. Subprocess stdout/stderr are collected via `await proc.communicate()`, which is non-blocking at the asyncio level.

### HEALTHY — All SQLite operations use `aiosqlite`

`cache.py`, `portfolio.py`, `log.py` all use `aiosqlite` with proper `await db.execute()` / `await cur.fetchone()` / `await db.commit()`. No blocking stdlib `sqlite3` usage found.

### HEALTHY — `aiohttp` used correctly throughout

`cmc_client.py` uses `aiohttp.ClientSession.request()` with `async with` and properly manages session lifecycle (`close()` method). Correct async HTTP.

### CONCERN — No `asyncio.TaskGroup` / cancellation scope usage

The codebase uses raw `asyncio.wait_for()` and `asyncio.create_task()` but does not use `TaskGroup` (Python 3.11+) for structured concurrency. When multiple async tasks are spawned for parallel execution (see Section 2), there is no structured scope to ensure they all complete or cancel together on shutdown.

**Recommendation**: When refactoring for parallel execution (Section 2 opportunities), consider using `asyncio.TaskGroup` (or `contextlib.AsyncExitStack`) to manage task lifetimes.

### CONCERN — No explicit timeout on `agent.main_loop()` shutdown

While `_shutdown_requested` is set by signal handlers, the main loop relies on the `asyncio.wait_for(timeout=...)` timeout to cycle. If the RPC or CMC call in `run_cycle()` hangs, the agent will be stuck until that call returns, because `_shutdown_requested.wait()` is a no-op while another coroutine is running.

**Recommendation**: Add an overall cycle timeout using `asyncio.wait_for(self.run_cycle(), timeout=120)` so a single hung cycle does not block shutdown.

---

## 5. Recommended Refactors

### Refactor 1 — Async-ify Quoter (CRITICAL, high effort)

**Priority:** Critical
**Files:** `src/quoter.py`

Make all public methods async and run synchronous web3 calls in a thread pool:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

class Quoter:
    def __init__(self, rpc_url: str = BSC_RPC_URL) -> None:
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def estimate_slippage_single(self, ...):
        loop = asyncio.get_running_loop()
        def _sync_quote(fee):
            # existing synchronous web3 call logic
            ...
        # Run all 4 fee tiers in parallel
        results = await asyncio.gather(
            *[loop.run_in_executor(self._executor, _sync_quote, fee) for fee in PCS_FEE_TIERS]
        )
        # pick best result
        ...
```

**Note:** Do NOT use `asyncio.to_thread()` for 4 sequential blocking calls — that still serializes them. Use `run_in_executor` with a thread pool to achieve true parallelism.

### Refactor 2 — Parallel forced sells (MEDIUM, low effort)

**Priority:** Medium
**File:** `src/agent.py`

Extract forced sell execution to `asyncio.gather()`:

```python
async def _exec_forced_sell(self, sell: dict) -> None:
    sym = sell["token"]
    price = sell["price"]
    pos = self.portfolio.positions.get(sym)
    units = pos["units"] if pos else 0.0
    if self.mode != "paper":
        swap_result = await self.twak.swap(units, sym, CASH_CURRENCY, slippage=0.5)
        tx_hash = swap_result.get("tx_hash") or ""
    else:
        tx_hash = f"0xSELL_PAPER_{sym}"
    await self.portfolio.close_position(sym, price, tx_hash)

# In run_cycle():
if forced_sells:
    await asyncio.gather(*[self._exec_forced_sell(s) for s in forced_sells])
```

### Refactor 3 — Async logging with fire-and-forget tasks (MEDIUM, low effort)

**Priority:** Medium
**File:** `src/log.py`

Add an async variant and update `decision.py` to use it:

```python
async def log_trade_async(...) -> None:
    # async SQLite insert
    ...

def log_trade(...):  # keep sync for hot paths
    logger.info("TRADE | ...")
```

In `decision.py`, queue the log as a background task:
```python
asyncio.create_task(log_trade_async(...))  # fire-and-forget, non-blocking
```

### Refactor 4 — Add cycle timeout guard (LOW, low effort)

**Priority:** Low
**File:** `src/agent.py`

Wrap `run_cycle()` in `asyncio.wait_for()` with a generous timeout:

```python
try:
    await asyncio.wait_for(self.run_cycle(), timeout=120)
except asyncio.TimeoutError:
    logger.error("Cycle %d timed out after 120s — skipping", self._cycle_count)
```

### Refactor 5 — Guard `portfolio.positions` dict access (LOW, low effort)

**Priority:** Low
**File:** `src/decision.py`

Replace direct dict access with `.get()`:

```python
# Before
pos = self.portfolio.positions[position_token]

# After
pos = self.portfolio.positions.get(position_token)
if not pos:
    continue
```

### Refactor 6 — Parallel TWAK swaps in decision loop (MEDIUM, medium effort)

**Priority:** Medium
**File:** `src/decision.py`

Collect all swap coroutines and execute with `asyncio.gather()`:

```python
# Build list of (token, swap_coro) pairs
swap_coros = []
for token, amount in _split_across_basket(total_size, basket):
    if os.getenv("AGENT_MODE") != "paper":
        swap_coros.append(
            (token, self.twak.swap(amount, CASH_CURRENCY, token, slippage=0.5))
        )

# Execute all swaps concurrently
if swap_coros:
    results = await asyncio.gather(*[c for _, c in swap_coros], return_exceptions=True)
    for (token, _), result in zip(swap_coros, results):
        if isinstance(result, Exception):
            logger.error("Swap %s failed: %s", token, result)
            continue
        # process result
```

---

## Summary

| Category | Count | Highest Severity |
|----------|-------|------------------|
| Blocking calls | 3 | CRITICAL |
| Parallelization opportunities | 5 | HIGH |
| Exception handling gaps | 5 | MEDIUM |
| Event loop concerns | 2 | CRITICAL |

**The single most urgent fix** is async-ifying `src/quoter.py`. Every call to `estimate_slippage_single()` or `get_balance()` blocks the entire event loop for up to 2 seconds, preventing the agent from responding to shutdown signals, processing CMC data, or writing to the trade journal during that window. This is a correctness and safety issue, not just a performance issue.