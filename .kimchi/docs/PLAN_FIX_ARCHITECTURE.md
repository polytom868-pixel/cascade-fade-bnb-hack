# CascadeFade — Architecture Audit & Fix Plan
**Auditor:** kimchi sub-agent (read-through, zero edits)
**Date:** 2026-06-21
**Scope:** `agent.py`, `decision.py`, `risk.py`, `config.py`, `db_base.py`, `portfolio.py`

---

## Findings Summary

| Severity | Count |
|---|---|
| CRITICAL | 4 |
| HIGH | 5 |
| MEDIUM | 6 |
| LOW | 4 |
| **Total** | **19** |

---

## Issue Table

| # | File | Line | Issue | Severity | Exact Replacement |
|---|---|---|---|---|---|
| 1 | `decision.py` | 148 | **Bug — `remove()` called synchronously before TWAK swap resolves.** The in-memory position is popped, but `close_position()` (async DB sync) is never called. DB row stays `open=1`. Next cycle re-enters the sell loop for the same token (key removed from dict, so no infinite loop), but `close_position()` never fires → PnL never computed, `open=0` never written. | CRITICAL | Replace lines 147–149 with an async helper. See Fix 1 below. |
| 2 | `decision.py` | 148 | **Bug — `log_trade()` is synchronous but imported as a bare function call.** `log_trade` (src/log.py:153) is `async def log_trade(...)`. Call site at decision.py:149 is `log_trade(...)` (no `await`). Trade never recorded. | CRITICAL | Change `log_trade(...)` at decision.py:149 and 193 to `await log_trade(...)`. |
| 3 | `agent.py` | 115 | **Bug — `_connect()` called twice in `setup()` without deduplication.** `setup()` calls `await self.portfolio.initialize_cash(...)` then immediately calls `await self.portfolio._connect()` again. `_connect()` calls `ensure_db` which reuses the same connection if it's already open (no harm), but pattern is fragile. | MEDIUM | See Fix 3 below. |
| 4 | `agent.py` | 42–45 | **Bug — `_signal_handler` set as both SIGINT and SIGTERM handler; runs in main thread not event loop thread.** On Windows, `signal.signal()` only works in the main thread. On Unix with asyncio, signal handlers run in the main thread's signal context, not the event loop thread. The handler calls `_shutdown_requested.set()` which is thread-safe for `asyncio.Event`, but `main_loop()` will be blocked inside `asyncio.timeout()` waiting — the signal interrupt won't break the wait. | HIGH | See Fix 4 below. |
| 5 | `agent.py` | 80–86 | **Bug — nested `_handle_sigint` registered inside `__init__`.** Second handler registered overwrites the module-level `_signal_handler`. Both fire on SIGINT (double-log), only the inner one fires on SIGTERM (contradicting the module-level `signal.signal(signal.SIGTERM, _signal_handler)` intent). SIGTERM goes to outer `_signal_handler`, SIGINT goes to inner `_handle_sigint`. | MEDIUM | Remove inner `_handle_sigint` entirely. Keep only module-level handlers. |
| 6 | `agent.py` | 244–265 | **Bug — `main_loop` busy-waits on SIGTERM without cancellation.** `asyncio.timeout(wait_for(...))` cannot be cancelled by a signal in Python <3.11; in 3.11+, `asyncio.timeout` uses `asyncio.timeout.cancel()` which hooks into the task cancellation mechanism, but only if `wait()` is awaiting. A SIGTERM arrives, sets the event, but the `async with asyncio.timeout: await wait()` is still inside the `with` block — it must wait for the next iteration to check `is_set()`. On a 30-minute interval, this means up to 30 minutes of delay before shutdown. | HIGH | See Fix 6 below. |
| 7 | `agent.py` | 111 | **Bug — WAL checkpoint after `initialize_cash()` but before any trades.** `initialize_cash()` commits a row to `portfolio_snapshots` but does not call `await db.commit()` inside itself. Looking at `portfolio.py:initialize_cash`, it does call `await db.commit()`. However, the WAL checkpoint `PRAGMA wal_checkpoint(TRUNCATE)` runs against `db` returned by `_connect()` — if `initialize_cash()` already committed and closed its transaction, this is fine. But `_connect()` may return a different connection object if `ensure_db` creates a new one. | LOW | Add explicit commit before checkpoint: `await db.commit()` before the `wal_checkpoint` call. |
| 8 | `agent.py` | 271 | **Bug — `self.portfolio.positions.get(sym)` may return stale data.** `_execute_sell` reads from `self.portfolio.positions` (in-memory dict) for `units`. But decision.py already called `self.portfolio.remove(sym)` synchronously. So `_execute_sell` gets `units=0.0` for any position that went through decision.py's sell path. Only forced sells (stop-loss/take-profit from `run_cycle` phase 4) read correct units because those positions haven't been removed yet. | HIGH | `_execute_sell` should fetch `units` from `self.portfolio.get_positions()` (DB query) or pass the units from the call site. |
| 9 | `decision.py` | 148 | **Bug — DB transaction never opened for `remove_position_from_db`.** `decision.py` calls `self.portfolio.remove(position_token)` (in-memory dict), then `log_trade(...)` (sync call, should be async), but never calls `remove_position_from_db()`. The DB `positions` row stays `open=1`. Next `get_positions()` query returns this token again, but it's no longer in the in-memory dict — no infinite loop, but stale DB state. | HIGH | Add `await self.portfolio.remove_position_from_db(position_token)` after `remove()`. See Fix 9 below. |
| 10 | `decision.py` | 62, 72 | **Missing return type hints.** `DecisionEngine.run_cycle` and `DecisionEngine.evaluate` have no return type annotations. | MEDIUM | `async def run_cycle(...) -> dict[str, Any]:` and `async def evaluate(...) -> dict[str, Any]:` |
| 11 | `decision.py` | 55 | **Missing type hints on `__init__` params.** `twak_client`, `portfolio`, `risk`, `signal_engine` are all untyped. | MEDIUM | `def __init__(self, twak_client: TWAKExecutor, portfolio: Portfolio, risk: RiskGuard, signal_engine: SignalEngineClass) -> None:` |
| 12 | `decision.py` | 37, 47, 31 | **Missing return type hints on module-level functions.** `_size_position`, `_split_across_basket`, `_build_narrative_map` are untyped. | LOW | `-> float:`, `-> list[tuple[str, float]]:` (replace `List[Tuple` with modern syntax), `-> dict[str, str]:` |
| 13 | `risk.py` | 104 | **Signature mismatch — `pre_trade_check` param names don't match call site.** `risk.py` defines `pre_trade_check(self, value, slippage_pct, held_count)` (params: dict, float, int). At `decision.py:141` it is called as `pre_trade_check({...}, value, 0)` — `value` (float) is passed to the `slippage_pct` position (expects float) and the dict is passed to `value` — actually this is correct order. But at `decision.py:184`: `pre_trade_check({"total": ..., "drawdown_pct": 0}, amount, 0)` — `amount` (float, trade size) is passed to `slippage_pct`. This is intentional (reusing the function for buy size as slippage proxy), but undocumented. | MEDIUM | Add docstring to `pre_trade_check` noting that `slippage_pct` accepts either slippage or trade amount as a "cost" proxy. Or rename to `pre_trade_check(value, cost_pct, held_count)`. |
| 14 | `risk.py` | 134 | **Missing `slippage_pct` param type hint.** `pre_trade_check(self, value: dict[str, Any], slippage_pct: float, held_count: int) -> dict[str, Any]` — the `value` dict signature is wrong per the callers (callers pass `{"total": ..., "drawdown_pct": 0}` or `{"total": ...}`). | LOW | Update to `value: dict[str, Any]` (already correct) — no fix needed here, just flag for clarity. |
| 15 | `config.py` | 5 | **`# noqa: E402` suppresses real import order issue.** `db_base.py` is imported before any project modules, but `db_base.py` only has constants and one async helper — no circular dependency risk. The `# noqa` is acceptable but should be removed with a comment explaining why it was added. | LOW | Replace `# noqa: E402` with `# noqa: E402  # db_base has no circular dep; imported first for WAL_AUTOCHECKPOINT` |
| 16 | `db_base.py` | 15 | **`busy_timeout=30000` hardcoded alongside `BUSY_TIMEOUT_MS = 30000` constant.** The constant exists in the module but is not used. DRY violation. | LOW | `await conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")` |
| 17 | `agent.py` | 155 | **Missing return type hint on `health_check`.** Returns `None`. | LOW | `async def health_check(self) -> None:` — already present, OK. |
| 18 | `agent.py` | 244 | **`asyncio.timeout` requires Python 3.11+.** Project claims Python 3.11+. No guard. | LOW | Add `assert sys.version_info >= (3, 11), "Python 3.11+ required for asyncio.timeout"` in `main()` or `Agent`. |
| 19 | `portfolio.py` | 68 | **`_row_to_position` returns `"amount"` but in-memory dict uses `"units"`.** `Portfolio._row_to_position` (used by `get_positions()` / DB path) returns `r[3]` as `"amount"`. The in-memory dict (used by decision.py) uses `"units"`. `decision.py` reads `pos["units"]` successfully from the in-memory dict. Forced sells in `agent.py:271` read `pos["units"]` from `self.portfolio.positions`. Both work. However, any code that calls `get_positions()` then reads `["units"]` will get a KeyError — it should read `["amount"]`. This is a silent API inconsistency. | HIGH | Rename in-memory key from `"units"` to `"amount"` throughout, OR add a compatibility property. See Fix 19 below. |

---

## Fix Specifications

### Fix 1 — `decision.py` line 148: Async DB sync for sells

**Problem:** `self.portfolio.remove(position_token)` is sync; `remove_position_from_db()` is async and never called.

**Replacement** (replace lines 145–149):
```python
            # TWAK swap: sell token -> USDT
            units = pos["units"]
            if os.getenv("AGENT_MODE", "paper") == "paper":
                tx_hash = f"0xSELL_PAPER_{position_token}"
            else:
                swap_result = await self.twak.swap(units, position_token, CASH_CURRENCY, slippage=0.5)
                tx_hash = swap_result.get("tx_hash") or (
                    swap_result.get("data", {}).get("txHash")
                    if isinstance(swap_result.get("data"), dict) else None
                )
            self.portfolio.remove(position_token)
            await self.portfolio.remove_position_from_db(position_token)
            await log_trade("SELL", position_token, units, price, value, tx_hash=tx_hash)
```

### Fix 2 — `decision.py` lines 149, 193: Await async `log_trade`

**Problem:** `log_trade` is `async def` but called without `await`.

**Replacement line 149:**
```python
            await log_trade("SELL", position_token, units, price, value, tx_hash=tx_hash)
```

**Replacement line 193:**
```python
            await log_trade("BUY", token, units, price, amount, tx_hash=tx_hash)
```

### Fix 3 — `agent.py` lines 111–115: WAL checkpoint needs explicit commit

**Problem:** `wal_checkpoint(TRUNCATE)` may run against a connection with pending writes if `initialize_cash`'s commit hasn't flushed.

**Replacement** (replace lines 110–115):
```python
        # Initialize portfolio cash
        await self.portfolio.initialize_cash(self.initial_cash)
        logger.info("Portfolio initialized: cash=$%.2f", self.initial_cash)

        # WAL checkpoint to reduce DB file size on startup
        db = await self.portfolio._connect()
        await db.commit()          # ensure initialize_cash writes are flushed
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await db.commit()
```

### Fix 4 — `agent.py` lines 42–45, 80–86, 244–265: SIGTERM graceful shutdown

**Problem:** Signal arrives during `asyncio.timeout()` wait; shutdown延迟 up to `interval_minutes` (30 min default).

**Replacement `main_loop`** (replace lines 244–265):
```python
    async def main_loop(self) -> None:
        """Run trading loop until shutdown signal."""
        await self.setup()

        while not _shutdown_requested.is_set():
            try:
                # Wait for interval OR shutdown signal — whichever comes first
                async with asyncio.timeout(self.interval.total_seconds()):
                    await _shutdown_requested.wait()
            except asyncio.TimeoutError:
                # Interval elapsed normally — run cycle
                pass  # fall through to run_cycle

            # External SIGTERM/SIGINT may have set the event during the wait;
            # check before running cycle to avoid one extra cycle on shutdown.
            if _shutdown_requested.is_set():
                break

            await self.run_cycle()

        await self.shutdown()
```

Also **remove** the inner `_handle_sigint` from `__init__` (lines 80–86):
```python
    # DELETE these lines 80-86:
    #     def _handle_sigint(sig_num: int, _frame: Any) -> None:
    #         logger.warning("SIGINT received — requesting graceful shutdown...")
    #         _shutdown_requested.set()
    #     signal.signal(signal.SIGINT, _handle_sigint)
```

Module-level `_signal_handler` at line 42 is sufficient for both SIGINT and SIGTERM.

**Note on SIGTERM cancellation:** In Python 3.11+, `asyncio.timeout` hooks into task cancellation via `ShieldTermination`, so when `_shutdown_requested.set()` fires from a signal, the `wait()` inside `timeout` is cancelled and `TimeoutError` is NOT raised — the `with` block exits normally. This means the loop checks `is_set()` and breaks cleanly. If on Python 3.10 or earlier, add a version guard:
```python
if sys.version_info < (3, 11):
    # Fallback: poll every 5s instead of asyncio.timeout
    while not _shutdown_requested.is_set():
        try:
            await asyncio.sleep(min(self.interval.total_seconds(), 5.0))
        except asyncio.CancelledError:
            break
        if _shutdown_requested.is_set():
            break
        if True:  # interval elapsed
            await self.run_cycle()
else:
    while not _shutdown_requested.is_set():
        try:
            async with asyncio.timeout(self.interval.total_seconds()):
                await _shutdown_requested.wait()
        except asyncio.TimeoutError:
            pass
        if _shutdown_requested.is_set():
            break
        await self.run_cycle()
```

### Fix 6 — `agent.py` line 271: `_execute_sell` reads stale `units`

**Problem:** `self.portfolio.positions.get(sym)` returns None because decision.py already called `remove()`.

**Replacement `_execute_sell`** (replace lines 266–282):
```python
    async def _execute_sell(self, sell: dict[str, Any], price_map: dict[str, float]) -> None:
        """Execute a single forced sell (stop-loss or take-profit)."""
        sym = sell["token"]
        price = sell["price"]
        # Read from DB to avoid stale in-memory dict (decision.py may have
        # already removed the position).
        positions = await self.portfolio.get_positions()
        pos = next((p for p in positions if p["symbol"] == sym), None)
        units = pos["amount"] if pos else 0.0
        try:
            if self.mode != "paper":
                result = await self.twak.swap(units, sym, CASH_CURRENCY, slippage=0.5)
                tx_hash = result.get("tx_hash") or ""
            else:
                tx_hash = f"0xSELL_PAPER_{sym}"
            await self.portfolio.close_position(sym, price, tx_hash)
            logger.info("Forced sell OK: %s reason=%s price=%.4f tx=%s", sym, sell["reason"], price, tx_hash)
        except Exception as exc:
            logger.warning("Forced sell %s failed: %s", sym, exc)
```

### Fix 9 — `decision.py`: Add `remove_position_from_db` call

**Problem:** DB `positions` row stays `open=1` after sell.

**Replacement** (add after line 148, before log_trade):
```python
            self.portfolio.remove(position_token)
            await self.portfolio.remove_position_from_db(position_token)
            await log_trade(...)
```

`remove_position_from_db` in portfolio.py already calls `close_position(symbol, 0.0, "")` which sets `open=0`.

### Fix 19 — `portfolio.py`: Unify `units` vs `amount` field name

**Problem:** In-memory dict uses `"units"`; DB row uses `"amount"` (via `_row_to_position`); forced sell reads `pos["units"]` but if position came from DB via `get_positions()`, it's `"amount"`.

**Replacement:** Rename in-memory key from `"units"` to `"amount"` in all four places:

`portfolio.py`:
- `__init__`: comment change only — dict is `{symbol: {"entry_ts": ..., "entry_price": ..., "units": ...}}`
- `add()` line: `"units": units,` → `"amount": units,` (also rename local var if desired)
- `total_exposure()`: `p.get("units", 0.0)` → `p.get("amount", 0.0)`
- `_row_to_position`: `r[3]` already maps to `"amount"` (consistent)

`agent.py` `_execute_sell`: `pos["units"]` → `pos["amount"]`

`decision.py`: `pos["units"]` at lines 140, 143, 175 → `pos["amount"]`

`risk.py check_exits`: reads `pos.get("entry_price", ...)` only, no units field — OK.

---

## Hidden Bugs (Missed in Prior Audits)

### H-1: `decision.py` sell path — two separate exit codepaths, only one works
- **Path A (decision.py evaluate):** `remove()` → `log_trade()` (sync, wrong) → no DB update → stale row.
- **Path B (agent.py forced sells):** `close_position()` → DB `open=0` → PnL computed. Works correctly.
- The decision.py sell path is broken and will leave zombie positions.

### H-2: `asyncio.gather` in `run_cycle` lines 163-167 uses correct `return_exceptions=True`
Verified — line 216 uses `return_exceptions=True`. No issue here. However, the Phase 1 gather (lines 163-167) does NOT use `return_exceptions`. If any of `get_held_symbols`, `get_positions`, or `get_cash_balance` raises, the entire cycle aborts. This is arguably correct (fail-fast on DB errors), but means one bad query kills the whole cycle.

### H-3: `Portfolio.positions` is not re-synced from DB between cycles
`decision.py` mutates `self.portfolio.positions` (add/remove). On next `run_cycle` call, `agent.py` calls `get_positions()` (DB query) to get `held_symbols` and `positions` (for forced sell check). But `decision.py` then reads from `self.portfolio.positions` (in-memory). These can diverge: if the agent crashes after `remove()` but before `remove_position_from_db()`, the in-memory dict is clean but DB is stale. The forced-sell loop at `agent.py:192–201` reads from the DB result (`positions` from Phase 1 gather), not the in-memory dict — so it handles this correctly. But `decision.py` reads in-memory. If a position was removed in-memory but the DB row is still `open=1`, decision.py won't see it again (good — no double sell), but the DB is poisoned.

### H-4: `agent.py` SIGTERM double-counts handler registration
`_signal_handler` at module level (line 42) and `_handle_sigint` inside `__init__` (line 80) both register for SIGINT. On first SIGINT, both fire, producing two "SIGINT received" log lines. The module-level handler fires first, then `__init__`'s handler fires second.

### H-5: `pre_trade_check` called with wrong `held_count=0` always
In decision.py, `pre_trade_check()` is called with `held_count=0` for both buy and sell decisions (lines 141, 184). The `MAX_POSITIONS` check in `pre_trade_check` (risk.py:157) is therefore bypassed for all trades. The position count guard is never enforced.

**Fix:** Pass actual held count:
```python
# In decision.py evaluate(), before buy loop:
held_count = len([p for p in self.portfolio.positions if p in basket])

# In sell loop:
held_count = len(self.portfolio.positions)
```

### H-6: `risk.py circuit_breaker()` uses `portfolio.peak_value` which may not exist
`circuit_breaker` does `peak_value = getattr(self.portfolio, "peak_value", portfolio_value)`. `Portfolio` has no `peak_value` attribute. So `getattr` always falls back to `portfolio_value`, meaning `circuit_breaker` always returns `drawdown_pct = 0`. The drawdown circuit breaker is permanently disabled.

**Fix:** Track peak value in Portfolio and expose it, or query `portfolio_snapshots.peak_value` directly:
```python
async def circuit_breaker(self, portfolio_value: float) -> tuple[bool, str]:
    db = await self.portfolio._connect()
    async with db.execute("SELECT MAX(peak_value) FROM portfolio_snapshots") as cur:
        row = await cur.fetchone()
    peak_value = row[0] if row and row[0] is not None else portfolio_value
    drawdown_pct = max(0.0, (peak_value - portfolio_value) / peak_value) if peak_value > 0 else 0.0
    ...
```

---

## Missing Type Annotations

| File | Location | Item | Fix |
|---|---|---|---|
| `decision.py` | 31 | `_build_narrative_map` | `-> dict[str, str]` |
| `decision.py` | 37 | `_size_position` | `-> float` |
| `decision.py` | 47 | `_split_across_basket` | `-> list[tuple[str, float]]` |
| `decision.py` | 55 | `__init__` params | `twak_client: TWAKExecutor, portfolio: Portfolio, risk: RiskGuard, signal_engine: SignalEngineClass` |
| `decision.py` | 62 | `run_cycle` | `-> dict[str, Any]` |
| `decision.py` | 72 | `evaluate` | `-> dict[str, Any]` |
| `risk.py` | 175 | `check_exits` | Already has full annotations |
| `risk.py` | 134 | `pre_trade_check` | Document `value` param shape in docstring |
| `config.py` | N/A | No functions — OK | — |
| `db_base.py` | 10 | `apply_pragmas` | Already annotated |
| `agent.py` | 54 | `__init__` | Already annotated |
| `agent.py` | 292 | `dry_run` | `-> list[dict[str, Any]]` |

---

## Architecture Smells

### AS-1: In-memory dict and SQLite are not kept in sync transactionally
`Portfolio.positions` (in-memory dict) and `positions` DB table diverge after every `add()`/`remove()` in decision.py. The `sync_position_to_db()` and `remove_position_from_db()` calls are fire-and-forget async calls made after the in-memory state is already mutated. If the async calls fail (exception), the in-memory state is already wrong and will stay wrong for the next cycle. Consider making in-memory mutations conditional on successful DB ops, or using the DB as the single source of truth and eliminating the in-memory dict entirely.

### AS-2: `signal_engine.evaluate()` called but result's `top_narrative`, `top_verdict` fields are used without schema validation
`decision.py` calls `self.signal_engine.evaluate()` and immediately accesses `signal_result.get("top_narrative", "")`, `signal_result.get("top_verdict", "AVOID")`, etc. No validation. If the signal engine returns a different schema (or an error dict), the decision engine will silently default to safe values but may not reflect actual signal intent. Add a Pydantic model or dataclass validation for `SignalResult`.

### AS-3: `CASH_CURRENCY` and `RISK_CURRENCY` defined in two places
`config.py` defines `CASH_CURRENCY = "USDT"` and `RISK_CURRENCY = "WBTC"`. `decision.py` defines its own `CASH_CURRENCY = "USDT"` and `RISK_CURRENCY = "WBTC"` at module level. These must stay in sync manually. `agent.py` imports `CASH_CURRENCY` from `decision.py`. Remove the `decision.py` definitions and import from `config.py`.

### AS-4: `agent.py` imports `CASH_CURRENCY` and `RISK_CURRENCY` from `decision.py` — wrong direction
`decision.py` is the business logic module; `config.py` is the config module. Config constants should be imported from `config.py`, not from `decision.py`. `agent.py` should import `CASH_CURRENCY` from `config.py`. Fix: remove import from `decision.py`; add `CASH_CURRENCY` to `config.py` exports; import from `config.py` in `agent.py`.

### AS-5: `log.py` has both a `TradeLogger` class and a `log_trade` function
`TradeLogger` is used as `self.trade_logger` in `Agent`. `log_trade` is a standalone function imported by `decision.py`. They likely both write to the same `trades` table. Two separate code paths to the same destination create divergence risk. Consolidate into one interface.

### AS-6: `Quoter` instantiated conditionally but used unconditionally
`agent.py:59`: `self.quoter = Quoter() if self.mode != "paper" else None`. But `_execute_sell()` and other methods never call `self.quoter` directly — all swap execution goes through `TWAKExecutor`. The quoter is only used in `setup()` for connectivity check. Consider removing the null check complexity or document why it's conditionally constructed.

---

## Verification Strategy

| # | Fix | Verification |
|---|---|---|
| 1, 9 | Async DB sync for sells | Add integration test: call `decision.evaluate()` with a held position, verify `positions` DB row has `open=0` after the call. |
| 2 | Await `log_trade` | Add integration test: execute buy or sell in paper mode, verify `trades` table has a row for that trade. |
| 3 | WAL checkpoint after explicit commit | Visual: verify `pragmas.py` test or add unit test calling `setup()` and checking DB WAL file size. |
| 4, 6 | SIGTERM graceful shutdown | Send SIGTERM to running agent process; verify shutdown completes within 5 seconds regardless of interval setting. |
| 8 | `_execute_sell` DB fetch | Unit test: pre-populate portfolio DB with a position, call `remove()` in-memory (simulating decision.py), then call `_execute_sell`, verify correct `units` fetched. |
| H-5 | `held_count=0` fix | Add `len(self.portfolio.positions) >= MAX_POSITIONS` assertion test. |
| H-6 | `circuit_breaker` peak_value | Add test: set peak in `portfolio_snapshots`, call `circuit_breaker` with current value below peak, assert drawdown pct is computed. |
| 19 | `units`→`amount` rename | Full project grep for `"units"` key reads; replace with `"amount"`. Run existing tests. |

---

## Decision Log

| Decision | Rationale |
|---|---|
| Keep `asyncio.timeout` pattern (Fix 4) | Correct pattern for 3.11+; add version guard for 3.10 fallback rather than removing the optimization. |
| Not remove in-memory dict entirely | Decision.py synchronous reads from `self.portfolio.positions` are used for sell-loop iteration. Removing it requires making all decision logic async-first. Accept as medium-term debt. |
| Add version guard for Python 3.11 | Project claims 3.11+, but no runtime check exists. Add `assert sys.version_info >= (3, 11)` in `main()` to fail fast on unsupported Python. |
| Keep `return_exceptions=True` only on forced-sell gather | Phase 1 gather (DB reads) intentionally fails fast; Phase 6 gather (forced sells) uses `return_exceptions=True` to handle partial failures. This is the correct trade-off. |
| Skip re-architecture of dual sync/async DB paths | Too large for a fix pass. Documented as AS-1. Recommend adding `async_ctx` wrapper in future. |

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Fix 4 (signal handling) still has race on Python 3.10 | Medium | Add explicit version guard; recommend Python 3.11+ only |
| Fix 19 (`units`→`amount`) may break other files not in audit scope | Medium | Grep entire `src/` tree for `"units"` before applying |
| Fix 1+9 may introduce new DB locking if `remove_position_from_db` is called inside an already-committed transaction | Low | `remove_position_from_db` opens its own `BEGIN IMMEDIATE` transaction |
| Fix 8 changes `_execute_sell` to always query DB | Low | Add DB index on `positions(symbol, open)` which already exists |