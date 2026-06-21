# CascadeFade — Performance Audit & Deduplication Report

**Date:** 2026-06-21
**Files Analyzed:** 18 Python files (2,830 total lines)
**Tooling:** `npx jscpd` (found 1 clone, 0.18% duplication)

---

## 1. Duplicated Code

### 1.1 SQLite PRAGMA Boilerplate (HIGH PRIORITY — Extract)

| File | Lines | Block |
|------|-------|-------|
| `src/log.py` | 40–43 | `await self._db.execute("PRAGMA journal_mode=WAL")` ... |
| `src/portfolio.py` | 50–54 | Same 4 lines, identical |

**Duplicate Block:**
```python
await self._db.execute("PRAGMA journal_mode=WAL")
await self._db.execute("PRAGMA synchronous=NORMAL")
await self._db.execute("PRAGMA foreign_keys=ON")
```

**Suggested Fix:** Add to `src/utils.py`:
```python
async def apply_db_pragmas(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA temp_store=MEMORY")
    await db.execute("PRAGMA cache_size=10000")
```
Then call `apply_db_pragmas(new_db)` inside `ensure_db()` in utils.py, and remove all call sites from `log.py`, `portfolio.py`, and `cache.py`.

**Files affected:** `log.py`, `portfolio.py`, `cache.py` (cache.py also has 3 of the same PRAGMAs).

---

### 1.2 `ensure_db` / Connection Reuse Pattern Duplication

`log.py`, `portfolio.py`, and `cache.py` each implement their own `async def _connect() -> aiosqlite.Connection` that calls `ensure_db()`. All three follow the exact same pattern:
1. Call `ensure_db(existing_conn, db_path)` 
2. If `new_db is not self._db`, set `self._db = new_db` and apply PRAGMAs
3. Return the connection

**Suggested Fix:** The `apply_db_pragmas` helper above (item 1.1) plus a shared `_shared_connect(self)` in a mixin or utility function would eliminate ~20 lines of duplication across 3 files.

---

## 2. Function Complexity

### 2.1 `DecisionEngine.evaluate` — ~140 lines (HIGH)

**File:** `src/decision.py`, lines ~58–200

The `evaluate` method is the largest single function in the codebase. It mixes:
- Risk guard calls (3 sequential awaits)
- Narrative extraction
- Full sell loop (nested logic, 35+ lines)
- Full buy loop (nested logic, 45+ lines)

**Suggested Split:**

| New Function | Responsibility | Approx Lines |
|---|---|---|
| `_sell_old_narratives()` | Iterate positions, decide sells | ~35 |
| `_execute_buys()` | Iterate basket tokens, execute buys | ~40 |
| `evaluate()` (refactored) | Risk guards → sell → buy → return | ~50 |

### 2.2 `Agent.run_cycle` — ~95 lines (MEDIUM)

**File:** `src/agent.py`, lines ~84–180

Acceptable complexity, but the forced-sells block inside `run_cycle` (lines ~130–160) is a self-contained 30-line loop that could be extracted to `_execute_forced_sells()`.

### 2.3 `SignalEngineClass._fetch_narrative_data` — ~45 lines, 4 nesting levels (MEDIUM)

**File:** `src/signal.py`, lines ~170–215

This method builds synthetic/narrative data using CMC quotes. The nested dict construction (lines ~192–209) has 4 levels of nesting and mixes real data with hardcoded fallback values. The `basket_data` list comprehension + averaging logic is dense enough to warrant extraction.

### 2.4 `Quoter.estimate_slippage_single` — ~70 lines, 3 nesting levels (LOW)

**File:** `src/quoter.py`, lines ~80–155

Functional but dense. The `price_map` → `ideal_out` computation block (lines ~103–112) could be `_compute_ideal_output()` and the fee-tier loop (lines ~115–145) could be `_try_fee_tier()`.

### 2.5 `Portfolio.compute_value` — ~45 lines, wide (LOW)

**File:** `src/portfolio.py`, lines ~175–220

Three responsibilities: sum positions, get peak from DB, record snapshot. Extracting `_sum_positions()` and `_update_peak()` would improve readability.

---

## 3. Magic Numbers & Constants

| Value | Location | Should Be |
|-------|----------|-----------|
| `300` | `src/cache.py:18` `CACHE_TTL_SECONDS = 300` | Already a named constant — **verify it is imported/used in `get_quote`, `get_trending`, `get_fear_greed`** (currently referenced only in comments and inlined in `.isoformat()` calls — **these are NOT using the constant**) |
| `22` (hours) | `src/risk.py:75` `hours_since < 22` | `HEARTBEAT_GRACE_HOURS = 22` in `risk.py` |
| `0.90` (exposure ratio) | `src/risk.py:117` `MAX_EXPOSURE_RATIO = 0.90` | Good — already named |
| `50` (ranking threshold) | `src/signal.py:72` `trending <= 10`, `trending <= 25` | `HIGH_TRENDING = 10`, `MODERATE_TRENDING = 25` |
| `500` (chars) | `src/twak.py:66` `result["error"] = stderr[:500]` | `MAX_ERROR_LEN = 500` |
| `5 * HEARTBEAT_SIZE_USD` | `src/risk.py:138` `min_portfolio_for_floor = HEARTBEAT_SIZE_USD * 5` | Named constant in the method — promote to class/module level |
| `0.999_999` (fallback rank) | `src/signal.py:209` `cmc_rank) or 999_999` | `DEFAULT_CMC_RANK = 999_999` |
| `30` (minutes in seconds calc) | `src/decision.py:132` `now - last < TRADE_INTERVAL_MINUTES * 60` | Acceptable as-is (already uses constant) |
| `"0xSELL_PAPER_"` | `src/agent.py:158` | `PAPER_TX_PREFIX = "0xSELL_PAPER_"` in config or utils |
| `"0xPAPER_"` | `src/decision.py:153` | `PAPER_TX_PREFIX_BUY = "0xPAPER_"` |
| `"paper"` | Multiple files | Already `AGENT_MODE` constant — ensure all `os.getenv("AGENT_MODE")` checks go through `src.config.AGENT_MODE` |
| `120` (seconds TWAK timeout) | `src/twak.py:42` `timeout: int = 120` | `TWAK_TIMEOUT_SECONDS = 120` in config |
| `0.6` (risk-off meme multiplier) | `src/signal.py:130` `adjusted * 0.6` | `MEME_RISK_OFF_MULTIPLIER = 0.6` |
| `1.1` (AI narrative multiplier) | `src/signal.py:133` `adjusted * 1.1` | `AI_NARRATIVE_BOOST = 1.1` |
| `0.1` (conviction decay rate) | `src/signal.py:118` `CONVICTION_DECAY_RATE = 0.10` | Already a named constant |
| `"RISK_ON"`, `"TRANSITION"`, `"RISK_OFF"` | Multiple files | Enum or string constants — currently duplicated across `signal.py`, `risk.py`, `decision.py` |

**Critical bug:** `CACHE_TTL_SECONDS = 300` is defined in `cache.py` but the actual TTL cutoff computation in `get_quote`, `get_trending`, and `get_fear_greed` hardcodes the same value inline (`timedelta(seconds=300)`) instead of using the named constant. This defeats the purpose of having the constant.

---

## 4. Dead Code / Unused Imports

### 4.1 Dead / Unused Functions

| Function | File | Issue |
|----------|------|-------|
| `_sum_position_values()` | `src/portfolio.py:43` | Defined and has docstring — **never called**. The `compute_value` method does its own inline sum instead. Remove or use it. |
| `async def log_decision()` | `src/log.py:98` | Defined — **never called** anywhere in the codebase. Dead code. |
| `_size_position()` | `src/decision.py:52` | Only called once inside `evaluate()`. Inlinable or could be kept as-is for readability. Low priority. |
| `_split_across_basket()` | `src/decision.py:57` | Only called once. Inlinable. Low priority. |

### 4.2 Stale / Incomplete Script

| Script | Issue |
|--------|-------|
| `scripts/test_signal.py` | Calls `SignalEngineClass()` with **no arguments**, but the class requires `cmc_client: CMCClient`. This will raise `TypeError` at runtime. The script is broken. |
| `scripts/test_data.py` | `cache = Cache()` created but **never used** — `set_quote`, `set_trending`, `set_fear_greed` are never called. |

### 4.3 Unused Imports

| File | Unused Import | Note |
|------|---------------|------|
| `src/signal.py:8` | `from src.config import CASH_CURRENCY, HEARTBEAT_SIZE_USD` | `CASH_CURRENCY` used? `HEARTBEAT_SIZE_USD` not used in signal.py |
| `src/signal.py:5` | `import statistics` | `statistics.mean` used in `_fetch_narrative_data` — **used** |
| `src/decision.py:10` | `from src.signal import REGIME_SIZING` | Used — OK |
| `src/decision.py:8` | `import datetime` | `datetime.datetime` used for entry_ts parsing — OK |
| `src/agent.py:13` | `from src.decision import CASH_CURRENCY, RISK_CURRENCY` | `CASH_CURRENCY` used in `run_cycle` — OK |
| `src/agent.py:20` | `from src.config import ALLOWLIST, ...` | `ALLOWLIST` imported — **not directly used** in agent.py (only via `NARRATIVE_BASKETS.values()`) |
| `src/cache.py:10` | `from src.utils import ensure_db` | Used in `_connect()` — OK |

### 4.4 Unreachable / Placeholder Code

| Location | Issue |
|----------|-------|
| `src/signal.py:188–215` | `_fetch_narrative_data` generates synthetic fallback values for ALL narrative data fields (`"basket_return_7d_pct"`, `"rsi_14": 50`, `"volatility_30d": 0.5`, etc.). These hardcoded fallbacks mean the signal engine is **not actually using real market data** for any scoring — it only gets real prices from CMC, then fills in everything else with constants. This is a design issue, not dead code, but it means `score_momentum`, `score_liquidity`, `score_attention` etc. operate almost entirely on fake data. |

---

## 5. Consistency Issues

### 5.1 `CASH_CURRENCY` / `RISK_CURRENCY` Defined Twice

| Definition | File |
|------------|------|
| `CASH_CURRENCY = "USDT"`, `RISK_CURRENCY = "WBTC"` | `src/config.py:59` |
| `CASH_CURRENCY = "USDT"`, `RISK_CURRENCY = "WBTC"` | `src/decision.py:24` |

`decision.py` imports both from `src.config` (line 10) but then **reassigns them locally**. `agent.py` imports them from `src.decision`. This circular-ish import dependency means config values are shadowed. Use ONLY `src.config` as the single source of truth.

### 5.2 Paper Mode Checks — Inconsistent Patterns

| Pattern | Files Using It |
|---------|---------------|
| `if self.mode != "paper":` | `agent.py:155` |
| `if os.getenv("AGENT_MODE", "paper") == "paper":` | `decision.py:115`, `decision.py:153` |
| `AGENT_MODE = os.getenv("AGENT_MODE", "paper")` | `config.py:56` |

`agent.py` stores mode in `self.mode` and checks it directly. `decision.py` re-reads the env var every call. This means `decision.py` ignores what `agent.py` set. **Fix:** Pass mode to decision engine, or have decision.py import from config (singleton, not env re-read).

### 5.3 Exception Types — Inconsistent

| File | Exception Used |
|------|----------------|
| `src/cmc_client.py:56` | `RuntimeError` for HTTP non-200 |
| `src/cache.py:54` | `ValueError` re-raised from aiosqlite |
| `src/quoter.py:87` | `return {"error": "Missing token addresses..."}` — returns dict, not raising |
| `src/portfolio.py:148` | Returns `{"error": ...}` dict — consistent with quoter |
| `src/twak.py:63` | `return {"error": ...}` — consistent dict-on-error |
| `src/agent.py:91` | `raise RuntimeError(...)` for connectivity |

Mixed strategies: some places raise exceptions, others return `{"error": ...}` dicts. Define a project-wide convention. Recommendation: **raise exceptions for fatal/precondition failures; return dicts for expected negative paths (e.g., "no liquidity found")**.

### 5.4 In-Memory vs Async DB State in Portfolio

`Portfolio.positions` is a plain `dict` (synchronous, in-memory). But `Portfolio.get_positions()` hits the SQLite DB. The decision loop reads `self.portfolio.positions[symbol]` synchronously for sell logic, but closing a position calls `await self.portfolio.close_position()` which is async. The `add()` and `remove()` methods mutate the in-memory dict synchronously. This dual-state model (in-memory + SQLite) is a known risk: if the process crashes between `add()` and `sync_position_to_db()`, the position is lost. **Not a bug for MVP**, but document this as a known limitation and consider a WAL-based write-ahead approach.

### 5.5 `log_trade` — Two Definitions

`src/log.py` has both `TradeLogger.log_trade()` (async, full signature) and a module-level `def log_trade()` (sync, simple signature). `decision.py` imports and calls the module-level one. The class method is defined but **never called**. The module-level function is used but has a different signature than the class method — this is confusing.

---

## 6. Refactor Priority List

Ranked by impact on maintainability, oldest first:

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| **P0** | `CACHE_TTL_SECONDS` not used — inline `300` in cache methods | 5 min | Correctness |
| **P0** | `scripts/test_signal.py` broken — wrong `SignalEngineClass` signature | 5 min | Correctness |
| **P1** | `CASH_CURRENCY`/`RISK_CURRENCY` redefined in `decision.py` | 5 min | Correctness |
| **P1** | Paper-mode inconsistency (`decision.py` re-reads env, ignores `agent.mode`) | 10 min | Correctness |
| **P1** | `src/log.py` has dead `log_trade` class method vs module-level function | 10 min | Correctness |
| **P2** | SQLite PRAGMA duplication across `log.py`, `portfolio.py`, `cache.py` | 15 min | Maintainability |
| **P2** | `_sum_position_values()` dead in `portfolio.py` | 5 min | Cleanup |
| **P2** | `log_decision()` dead in `log.py` | 5 min | Cleanup |
| **P2** | `decision.py` `evaluate()` — split into `_sell_old_narratives()` + `_execute_buys()` | 30 min | Maintainability |
| **P3** | `agent.py` `run_cycle()` — extract `_execute_forced_sells()` | 15 min | Maintainability |
| **P3** | `NARRATIVE_BASKETS` unused import in `agent.py` | 2 min | Cleanup |
| **P3** | Magic numbers: `HEARTBEAT_GRACE_HOURS`, `TWAK_TIMEOUT_SECONDS`, etc. | 20 min | Maintainability |
| **P3** | Signal engine `_fetch_narrative_data` uses 100% hardcoded fallback data | Design issue | Correctness |

---

## Summary

| Category | Count |
|----------|-------|
| Duplicate blocks (JS CPD) | 1 |
| Functions >50 lines | 3 (`evaluate`, `run_cycle`, `_fetch_narrative_data`) |
| Magic numbers (unnamed) | ~15 |
| Dead functions | 3 (`_sum_position_values`, `log_decision`, one of two `log_trade`) |
| Broken scripts | 1 (`test_signal.py`) |
| Consistency issues | 5+ |
| Priority P0 (correctness) issues | 2 |

The codebase is in reasonable shape for a Hackathon Day 1 submission. The main concerns are: (a) two correctness bugs (`CACHE_TTL_SECONDS` not wired, `test_signal.py` broken signature), (b) the `CASH_CURRENCY` dual-definition which could cause silent bugs, and (c) the SQLite PRAGMA duplication which is a maintenance hazard when changing WAL settings.