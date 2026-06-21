# Fix Plan: signal.py / cmc_client.py / cache.py

**Goal:** Eliminate all bugs, dead code, type hazards, and logic gaps in the signal engine, CMC client, and SQLite cache.

---

## Table: All Issues

| File | Line | Issue | Severity | Exact Replacement |
|---|---|---|---|---|
| signal.py | 7 | `import numpy as np` — imported but **never used** (only used for `isinstance` check on rsi_score, but `float()` cast handles it without numpy) | LOW | Delete the entire `import numpy as np` line |
| signal.py | 51,54,55,57,58,59,61,63,64 | **40 lines use semicolons to put 2 statements on one line** — triggers Ruff E701 | HIGH | Expand each to separate lines. E.g. `if rs > 1.15: score += 35` becomes `if rs > 1.15: score += 35` / `reasons.append(...)` on next line |
| signal.py | 53–64 | `score_momentum()` — all scoring branches use semicolons | HIGH | Same expansion fix |
| signal.py | 71–79 | `score_liquidity()` — semicolons | HIGH | Same expansion fix |
| signal.py | 86–91 | `score_attention()` — semicolons | HIGH | Same expansion fix |
| signal.py | 98–114 | `score_fundamental()` — semicolons | HIGH | Same expansion fix |
| signal.py | 121–127 | `compute_exhaustion_score()` — semicolons | HIGH | Same expansion fix |
| signal.py | 134–135 | `score_risk_adjustment()` — semicolons | HIGH | Same expansion fix |
| signal.py | 156 | `conviction_history: dict = None` — **mutable default `None` where `dict` expected** | CRITICAL | `conviction_history: dict | None = None` |
| signal.py | 206 | `conviction_history: dict = None` — same issue | CRITICAL | `conviction_history: dict | None = None` |
| signal.py | 239–241 | **3 statements on one line with semicolons** (two appends) | HIGH | Split into 2 lines |
| signal.py | 268 | `await self._fetch_narrative_data()` — **method called but NEVER DEFINED** | CRITICAL | Implement the method (see Missing Types section) |
| signal.py | 270 | `regime, reason = detect_market_regime(...)` — **`reason` value is declared and assigned but never used** | LOW | `regime, _ = detect_market_regime(...)` |
| signal.py | 262–266 | `SignalEngineClass.__init__`: `_last_prices` and `_last_scores` are declared and stored but **never read or written anywhere in the class** — dead instance variables | MEDIUM | Remove both lines, or wire them into `evaluate()` to actually implement price-change skipping |
| signal.py | 4 | `from src.config import CASH_CURRENCY, HEARTBEAT_SIZE_USD` — both imported but **never used** | LOW | Remove from import list |
| signal.py | 25–33 | `detect_market_regime()` uses hardcoded dummy values (45, 50, 0.02) inside `evaluate()` — the function parameters are bypassed | CRITICAL | `evaluate()` must pass real `bnb_dominance`, `fear_greed`, `mcap_change_7d` from CMC data. Stub until `_fetch_narrative_data()` is built |
| cmc_client.py | 79–81 | `_ensure_session()` is defined and calls `_get_session()` but is **never called anywhere** — dead code | LOW | Delete the entire method |
| cmc_client.py | 54–58 | `self._headers` sets `Accept-Encoding: gzip` AND `auto_decompress=True` — both decompress gzip. `auto_decompress=True` (aiohttp default) makes `Accept-Encoding` redundant. | LOW | Either remove `Accept-Encoding` header or remove `auto_decompress=True` from `ClientSession`. Prefer: keep `Accept-Encoding: gzip` for explicitness, remove `auto_decompress=True` since the session is recreated in retry logic too |
| cmc_client.py | 64 | `atexit.register(self._sync_close)` in `__init__` — **each new CMCClient instance registers an atexit handler**. Creating 2 instances = 2 handlers = double-close. Also `__del__` emits a warning if `close()` was not called, but if atexit already closed it, `__del__` sees `closed=True` and is silent. | HIGH | Remove `atexit.register()`. Session cleanup must be explicit: document that callers must `await client.close()`. OR make it a module-level singleton to avoid multiple registrations. |
| cmc_client.py | 152–161 | **Session recreation in retry loop is dead code**: condition `if self._session is None or self._session.closed` — session is persistent and shared; `session.get()` never closes it. The only way `_session.closed` becomes `True` is if `close()` was explicitly called, in which case recreating it mid-retry is wrong. | HIGH | Delete the entire `if self._session is None or self._session.closed:` block (lines 152–162). Session should stay open across retries. |
| cmc_client.py | 137 | `last_error: Exception | None = None` — local variable but `Exception` (old-style class) is fine here; no fix needed | — | No change |
| cmc_client.py | 140–141 | **Double sleep in retry**: when `resp.status == 429`, `asyncio.TimeoutError` is raised which matches the `except` clause, then `asyncio.sleep(CMC_RETRY_BACKOFF * (2 ** attempt))` runs. But the outer `retry_async` in `_request()` also sleeps on each retry. This double-backs off. However `get_bulk_quotes()` has its **own independent retry loop** and does NOT use `_request()` — so `_request`'s `retry_async` is only used by `get_fear_greed` and `get_dex_trending`. For `get_bulk_quotes` the double-backoff does NOT apply. | LOW | Verify callers. `_request` callers: `get_fear_greed`, `get_dex_trending`. Both would double-sleep on 429. Fix: remove `asyncio.TimeoutError` from the raised exception for 429, use a custom `RateLimitError` that `_request`'s `retry_async` does NOT catch (so it re-raises and skips the manual sleep). Or just remove the manual `await asyncio.sleep` from the retry loop in `get_bulk_quotes`. |
| cmc_client.py | 145–149 | In `get_bulk_quotes` retry loop, on success `_do()` inner function is never reached — the `async with session.get(...)` call is **outside** `_do()` in the outer loop. The `_do()` inner function is defined but only called via `_request()`, which is NOT used by `get_bulk_quotes`. | HIGH | `get_bulk_quotes()` retry loop has its own `async with session.get` directly in the outer loop — the `_do()` function at line 89 is unreachable from `get_bulk_quotes`. This is confusing dead code. The retry in `get_bulk_quotes` works correctly via the outer `for attempt in range(CMC_RETRIES)` loop. No functional bug but the structure is misleading. |
| cmc_client.py | 243–253 | `_sync_close()`: if a running event loop exists, the function silently **does nothing** (passes). The session stays open. At Python shutdown, this leaks. | HIGH | Change the `else: pass` to `asyncio.get_event_loop().call_later(0.1, lambda: None)` — or better: remove atexit entirely (per above fix) and document explicit close requirement |
| cache.py | 21 | `_checkpoint_done: bool = False` is a **class variable** — shared across ALL Cache instances. If instance A runs checkpoint, `Cache._checkpoint_done = True`, instance B will skip checkpoint even though its DB is a different file (or even unconnected). | CRITICAL | Change to `self._checkpoint_done: bool = False` (instance variable) initialized in `__init__` |
| cache.py | 31 | `PRAGMA wal_checkpoint(TRUNCATE)` is **blocking** — it must acquire EXCLUSIVE access to checkpoint. If `busy_timeout=30000` is set and other DB ops are in-flight, `_connect()` blocks for up to 30 seconds. Also calling `_gc_expired()` immediately after checkpoint on the same connection is redundant (both are writes). | MEDIUM | (a) Move checkpoint out of `_connect()` to a background task running every N minutes. (b) Or call `PRAGMA wal_checkpoint(PASSIVE)` instead of `TRUNCATE` — PASSIVE does not block, though it may not fully truncate the WAL file. Better: separate checkpoint into its own scheduled coroutine, not on every `_connect()` |
| cache.py | 24 | `new_db = await ensure_db(self._db, self._db_path)` — the return is only compared by identity. `ensure_db` always opens a new connection even when the existing one is healthy, because `hasattr(db, '_connection')` is always `True` and `db._connection is not None` is always `True` for a valid connection — so it always returns `db` unchanged. | LOW (works but misleading) | The liveness check passes for any non-None, non-closed connection. This is correct behavior for aiosqlite 0.22.1 where `_connection` is always set. Document intent, or replace with a lighter ping: `await db.execute("SELECT 1")` |
| cache.py | 147 | `_gc_expired()` is called inside `_connect()` — **every `_connect()` call triggers a DELETE on all 3 tables**. Under high frequency `_connect()` calls, this causes repeated full-table scans for expiry. | MEDIUM | Move `_gc_expired()` out of `_connect()`. Run as a scheduled task every 10 minutes or once per agent cycle, not on every DB access |
| cache.py | 24,47 | `_connect()` is **not thread-safe**: if two coroutines call `_connect()` concurrently before either sets `self._db`, both will call `ensure_db`, open connections, and one will overwrite the other. In aiosqlite, multiple connections to the same DB file is allowed (WAL mode), but `self._db` will be the last one written. | MEDIUM | Add an `asyncio.Lock` to `_connect()`: `self._lock = asyncio.Lock()` in `__init__`, then `async with self._lock: new_db = await ensure_db(...)` |

---

## Hidden Bugs (Not Obvious from Surface Scan)

### H1 — `ensure_db` always returns the existing connection unchanged (cache.py:24)
`ensure_db` checks `hasattr(db, '_connection')`. In aiosqlite 0.22.1, `_connection` is ALWAYS set on any `aiosqlite.Connection` object. So for any non-None `db`, the function always returns `db` unchanged — it never actually reopens. The reconnect logic in `ensure_db` is dead code for all practical purposes. This happens to work correctly (the existing connection is fine), but it means the "reconnect if stale" comment is false. **Fix intent**: document that `ensure_db` is a no-op for live connections, or simplify to just return `db` with a lightweight liveness ping.

### H2 — `atexit` + `__del__` double-close: session leaks when event loop is absent (cmc_client.py:64)
`atexit.register(self._sync_close)` is called in `__init__`. At Python shutdown:
- If no running loop: `asyncio.run(self.close())` closes the session cleanly.
- If a running loop exists: `_sync_close` does `pass` (silent no-op). Session stays open → **resource leak**.
- `__del__` then fires and sees `closed=False`, emitting a `ResourceWarning`.
- The atexit handler already tried and failed silently; `__del__` just warns.

**Fix**: Remove `atexit.register()`. Force callers to `await client.close()`.

### H3 — `SignalEngineClass.evaluate()` hardcodes all regime parameters (signal.py:270)
```python
regime, reason = detect_market_regime(bnb_dominance=45, fear_greed=50, mcap_change_7d=0.02)
```
These constants mean `detect_market_regime` always returns `"TRANSITION"` regardless of market state. The entire regime detection logic is bypassed. Until `_fetch_narrative_data()` is built, this should at minimum raise a `NotImplementedError` or log a warning so the hardcoded path is visible.

### H4 — `_last_prices` and `_last_scores` are dead storage (signal.py:265–266)
Both are initialized and stored but never written or read. The comment says "Cache: skip recalc when price unchanged" but the cache is never consulted. Either implement the price-change skip optimization or delete the fields.

### H5 — Session recreation in `get_bulk_quotes` retry loop is unreachable dead code (cmc_client.py:160)
```python
if self._session is None or self._session.closed:
    self._session = aiohttp.ClientSession(...)
```
`session.get()` does not set `_session.closed = True`. The only way this path executes is if `close()` was called externally mid-retry — in which case the retry is pointless since the caller will have abandoned the request. **Delete it.**

### H6 — Class-level `_checkpoint_done` causes cross-instance state bleed (cache.py:16)
`Cache._checkpoint_done` is shared. If multiple `Cache` instances exist (e.g., one for quotes, one for trades), instance A's checkpoint marks `_checkpoint_done=True` and instance B skips its checkpoint even though B's DB is different. **Fix**: move to instance variable.

### H7 — Concurrent `_connect()` races (cache.py:23)
No lock on `_connect()`. Two simultaneous `_connect()` calls both evaluate `self._db is None` as True, both call `ensure_db()`, both set `self._db`. The second write wins; the first connection leaks (though SQLite WAL handles multiple connections). **Fix**: add `asyncio.Lock()`.

### H8 — `CACHE_TTL_SECONDS` defined in 3 places (cache.py:11, cmc_client.py:12, config.py:7)
- `cache.py` line 11: local constant `CACHE_TTL_SECONDS = 1800`
- `cmc_client.py` line 12: imports from `src.config`
- `config.py` line 7: canonical definition `CACHE_TTL_SECONDS = 1800`

The local constant in `cache.py` shadows the import. `cache.py` never imports from `config` — it has its own local copy. If `config.py` value changes, `cmc_client.py` sees the new value but `cache.py` does not. **Fix**: `cache.py` should `from src.config import CACHE_TTL_SECONDS` and delete its local definition.

---

## Missing Types

### M1 — `SignalEngineClass._fetch_narrative_data()` is not defined (CRITICAL)
`evaluate()` calls `await self._fetch_narrative_data()` but the method does not exist. This will raise `AttributeError` at runtime.

**Required signature:**
```python
async def _fetch_narrative_data(self) -> dict[str, dict]:
    """Fetch per-narrative data for all NARRATIVE_BASKETS tokens.

    Returns:
        dict[str, dict]: {narrative_name: {
            "relative_strength_vs_bnb_7d": float,
            "basket_return_7d_pct": float,
            "drawdown_from_30d_high_pct": float,
            "rsi_14": float,
            "volume_change_7d_pct": float,
            "liquidity_usd": float,
            "spread_pct": float,
            "trending_rank_avg": int,
            "social_volume_24h": int,
            "kaito_mindshare_surge": bool,
            "github_commits_7d": int,
            "developer_growth_30d_pct": float,
            "tvl_change_7d_pct": float,
            ...  # any keys referenced in scoring functions
        }}
    """
    ...
```

The method must populate all keys referenced in `score_*` functions. Until it is implemented, `evaluate()` should either stub with dummy data and log a warning, or return a placeholder result.

### M2 — `detect_market_regime()` return type is `Tuple[str, str]` but `reason` is unused
`reason` from the tuple is always discarded by callers. Either remove it from the return type or use it.

### M3 — `score_risk_adjustment()` — `np.ndarray` type guard is fragile (signal.py:141)
```python
if isinstance(rsi_score, (list, tuple, np.ndarray)):
    rsi_score = float(rsi_score[0]) if len(rsi_score) > 0 else 0.5
```
Checking for `np.ndarray` requires `numpy`. Since `numpy` is imported but `np` is never used elsewhere, this is the only dependency on numpy. Either (a) remove the check and just cast to float (which works for all numeric types), or (b) import `numpy.typing.NDArray` and type-guard properly.

### M4 — `score_attention()` `trending_rank_avg` type is `int` (returned by CMC) but could be `None`
`data.get("trending_rank_avg", 50)` — if the key is present but `None`, `get` returns `None` not the default. This would cause `if trending <= 10` to raise `TypeError`. Defensive fix: `int(data.get("trending_rank_avg") or 50)`.

---

## Logic / Performance Issues

### L1 — `score_attention()` rewards HIGH trending tokens (opposite of strategy)
`sentiment.py` buy rules say "token NOT in top-3 CMC DEX trending" (avoid hype). But `score_attention()` awards **+30 for trending <= 10** and **+20 for trending <= 25**. This scores HIGH-attention tokens as STRONG_LONG candidates — exactly what the strategy says to avoid. The "fade" logic is inverted here.

**Fix**: Invert the scoring — trending rank 1-3 should penalize (negative score), not reward.

### L2 — `_gc_expired()` runs on every `_connect()` call
Every `get_quote()`, `get_trending()`, `get_fear_greed()` calls `_connect()`, which calls `_gc_expired()`. Under high frequency (e.g., every 30 seconds), this fires a DELETE on 3 tables every call. For small tables this is fast but O(n). It should be a scheduled background task.

### L3 — WAL checkpoint on every first `_connect()` is wasteful
`checkpoint()` runs on the very first connection. For a brand-new DB with no WAL file, this is a no-op that still performs the PRAGMA call. For a production DB with WAL, it blocks writer access for the duration. Should be scheduled, not on-connect.

### L4 — `get_bulk_quotes` does not use `_request` — inconsistent error handling
`get_fear_greed` and `get_dex_trending` use `_request` (with `retry_async`), but `get_bulk_quotes` has its own retry loop with different backoff logic. The inconsistency makes it harder to reason about rate-limit behavior. Consider consolidating into `_request` or clearly documenting the divergence.

### L5 — `TOKEN_TO_NARRATIVE` is computed at import time but `decision.py` rebuilds it
`signal.py` line 37 builds `TOKEN_TO_NARRATIVE` from `NARRATIVE_BASKETS`. Then `decision.py` line 34 calls `_build_narrative_map()`. If `NARRATIVE_BASKETS` changes, both need to be updated. `signal.py`'s `TOKEN_TO_NARRATIVE` is **never used** (confirmed by grep). Dead import-level computation.

### L6 — `_NARR_WEIGHTS` is computed at import time but **never used**
Confirmed by grep across all source files. Dead module-level computation. Remove.

### L7 — `score_fundamental()` baseline utility adds score even for narratives with no data
Line 114: `else: score += 10; reasons.append(f"{narrative} baseline utility")` — any narrative that doesn't match a known category gets a flat +10. This could artificially inflate conviction scores for tokens with no data. Consider making this conditional on presence of any non-null data fields, or removing the baseline.

---

## Cheats to Remove

None found. No `# type: ignore`, `# noqa`, or `# pylint:` suppressions in any of the three files.

---

## Chunks

### Chunk 1: signal.py — Semicolon expansion + type fixes
**Scope**: signal.py lines 51–135 (all score functions), lines 156/206 (`dict = None`), lines 239–241 (3 statements), lines 262–266 (dead fields), imports.
**Depends On**: None
**Accept When**: `ruff check src/signal.py` passes with zero E701 errors; `mypy src/signal.py` passes (once `_fetch_narrative_data` is stubbed)
**Open Questions**: Should `_last_prices`/`_last_scores` be deleted or implemented? Currently treating as delete (dead code).

### Chunk 2: signal.py — Missing `_fetch_narrative_data()` implementation
**Scope**: Add `SignalEngineClass._fetch_narrative_data()` method; stub `evaluate()` regime params
**Depends On**: Chunk 1 (clean code first)
**Accept When**: `python3 -c "from src.signal import SignalEngineClass; import inspect; assert hasattr(SignalEngineClass, '_fetch_narrative_data')"` passes

### Chunk 3: cmc_client.py — Remove dead code, fix atexit, fix session recreation
**Scope**: cmc_client.py — delete `_ensure_session()`, remove `atexit.register()`, delete session-recreation block in retry loop, remove redundant `auto_decompress`, fix double-sleep for rate limits
**Depends On**: None
**Accept When**: `ruff check src/cmc_client.py` passes; no `atexit` import remains; no `self._session = aiohttp.ClientSession` outside `__init__`

### Chunk 4: cache.py — Fix `_checkpoint_done` scope, add lock, move GC/checkpoint out of `_connect`
**Scope**: cache.py — `_checkpoint_done` to instance variable; add `asyncio.Lock`; `_gc_expired()` moved to scheduled task; checkpoint moved out of `_connect()`
**Depends On**: None
**Accept When**: Multiple concurrent `Cache()` instances each independently run checkpoint once; concurrent `_connect()` calls are serialized by lock

### Chunk 5: Verify all three files pass syntax + import + type checks
**Scope**: Full verification
**Depends On**: Chunks 1–4
**Accept When**: `python3 -m py_compile src/signal.py src/cmc_client.py src/cache.py`; `ruff check src/signal.py src/cmc_client.py src/cache.py`; all imports resolve (`python3 -c "from src.signal import *; from src.cmc_client import *; from src.cache import *"`)

---

## Decision Log

- **Keep `numpy` import despite minimal use**: Removed — it was only for one `isinstance` check that can be replaced with `float()` cast. Saves a heavy dependency at import time.
- **`atexit` vs explicit close**: Opted for explicit close. `atexit` with async code is inherently unreliable (no event loop at shutdown time), and multiple-instance registration creates double-close risk.
- **WAL checkpoint TRUNCATE vs PASSIVE**: Use `PASSIVE` when moving checkpoint out of `_connect()`, or make it a scheduled background task. `TRUNCATE` blocks writers and is too heavy for on-connect.
- **Token-to-narrative mapping**: `signal.py`'s `TOKEN_TO_NARRATIVE` is dead; `decision.py` has its own. Intentionally leave `signal.py`'s version (may be needed if signal engine is expanded to per-token scoring later).
- **`score_attention()` inverted logic**: Flagged as logic bug. Whether to score trending-high or trending-low is a strategy decision — documented as L1 for implementer to decide direction.

---

## Verification Strategy

```bash
# 1. Syntax
python3 -m py_compile src/signal.py src/cmc_client.py src/cache.py

# 2. All imports resolve
python3 -c "from src.signal import *; from src.cmc_client import *; from src.cache import *"

# 3. Ruff: no E701 (multiple statements), no F401 (unused imports)
ruff check src/signal.py src/cmc_client.py src/cache.py

# 4. All functions defined
grep -n "^def " src/signal.py  # verify _fetch_narrative_data appears
grep -n "await self._fetch_narrative_data" src/signal.py  # count callers = should be 1

# 5. No dict=None defaults
grep -n "dict = None" src/signal.py  # should be 0 after fix

# 6. Cache: _checkpoint_done is instance variable
grep -n "_checkpoint_done" src/cache.py  # line 21 should be indented (self._checkpoint_done)

# 7. Cache: asyncio.Lock present
grep -n "asyncio.Lock\|_lock" src/cache.py  # should show lock creation and usage

# 8. CMC: atexit removed
grep -n "atexit" src/cmc_client.py  # should return 0 matches

# 9. Import check: no numpy in signal.py
grep -n "numpy\|import np" src/signal.py  # should be 0
```

---

## Risks

- **Risk: Removing atexit may leak sessions if callers forget `await close()`** — HIGH likelihood if callers don't update. **Mitigation**: Add explicit `await client.close()` to `agent.py` shutdown path and document in README.
- **Risk: Moving `_gc_expired()` to a scheduled task means expired entries may not be cleaned until the next schedule** — LOW likelihood. TTL-based reads already skip expired entries; GC is cosmetic (WAL size reclamation). **Mitigation**: Schedule every 10 minutes, which is sufficient.
- **Risk: Inverting `score_attention()` changes all historical conviction scores** — MEDIUM likelihood. This is a strategy change, not a bug fix. **Mitigation**: Document as intentional strategy correction, update tests.
- **Risk: `ensure_db` liveness check is a no-op** — LOW likelihood of regression. The function works as written for aiosqlite 0.22.1. **Mitigation**: Document the check's intent; do not "fix" it to reconnect since it would add latency on every call.