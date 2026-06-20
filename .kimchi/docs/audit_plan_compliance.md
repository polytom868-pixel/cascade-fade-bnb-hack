# CascadeFade — Plan/Architecture/Submission Compliance Audit

## Verdict: NEEDS_FIXES

---

## 1. Narrative Rotation Signal Engine

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| Narrative rotation engine with 10 baskets | PLAN.md §5 Phase 2, ARCHITECTURE.md §4, demo_script.md SCENE 2 | **YES** | `src/signal.py:14–213` (5 scoring functions), `src/config.py:108–118` (10 NARRATIVE_BASKETS) | Full 5-bucket scoring (momentum, liquidity, attention, fundamental, risk). Conviction history with decay. Top-narrative rotation signal. |
| Regime detection (RISK_ON / TRANSITION / RISK_OFF) | PLAN.md §2 Phase 2 Task 2.2 | **YES** | `src/signal.py:14–26` (`detect_market_regime`), `src/config.py:104–106` (`REGIME_SIZING`) | Three regimes with sizing multipliers (1.0 / 0.6 / 0.3). |
| 5-bucket scoring per narrative | ARCHITECTURE.md §4 Signal, PLAN.md Phase 2 Task 2.1 | **YES** | `src/signal.py:29–126` (score_momentum/liquidity/attention/fundamental/risk_adjustment) | BUCKET_WEIGHTS defined at line 11. Each bucket scores 0–100. |
| Exhaustion scoring | ARCHITECTURE.md §4 Signal | **YES** | `src/signal.py:97–108` (`compute_exhaustion_score`), `src/signal.py:123` (incorporated in score_risk_adjustment) | Penalties for parabolic returns + declining volume, social hype without holder growth, near-30d-high with declining volume, extreme volatility. Capped at 100. |
| Conviction decay | ARCHITECTURE.md §4 Signal | **YES** | `src/signal.py:159–162` (CONVICTION_DECAY_RATE = 0.10, applied when stale > 1 day) | `((1 - 0.10) ** days_stale)` applied per stale day. |
| Global scan + portfolio weights | ARCHITECTURE.md §4 Signal | **YES** | `src/signal.py:177–213` (`global_scan`) | Ranked narratives, squared-weight allocation, 35% max single-narrative weight. |
| Demo scene: regime detected, 5-bucket scores, top narrative | demo_script.md SCENE 2 | **YES** | `src/signal.py` overall | Narrative data is fetched and bucketed per `global_scan` output. |

---

## 2. TWAK Swap Execution

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| TWAK CLI wrapper | PLAN.md Phase 3 Task 3.1–3.2 | **YES** | `src/twak.py:25–171` (full TWAKExecutor class) | Subprocess wrapper for `twak swap`, `twak wallet balance`, `twak wallet address`, `twak compete register`. |
| `--chain bsc` always passed | ARCHITECTURE.md §5, PLAN.md Task 3.1 | **YES** | `src/twak.py:37` | Default chain is `bsc`. |
| `--json` for machine parseable output | ARCHITECTURE.md §5 | **YES** | `src/twak.py:37` | `json_output=True` default. |
| `--quote-only` preview | ARCHITECTURE.md §5 | **YES** | `src/twak.py:43` (`quote_only` param) | Passed through to TWAK CLI. |
| Slippage parameter | ARCHITECTURE.md §5 | **YES** | `src/twak.py:44–45` | `slippage` float passed as `--slippage`. |
| `twak compete register` | ARCHITECTURE.md §9, PLAN.md Phase 0 Task 0.8 | **YES** | `src/twak.py:140–143` (`compete_register`) | `--chain bsc --json` flags. |
| Swap execution in decision loop | PLAN.md Phase 3 Task 3.2, SUBMISSION.md | **PARTIAL** | `src/decision.py` (actions generated but actual swap call not wired through decision engine — see issue #1) | `decision.py:evaluate()` generates buy/sell actions and updates portfolio in-memory, but TWAK swap execution is not called from the decision engine. The `agent.py` main loop calls `decision.run_cycle()` but `run_cycle()` result does not trigger `twak.swap()`. The TWAKExecutor is passed to DecisionEngine but never called within `evaluate()`. See **Critical Bug #1**. |
| Demo scene: TWAK swap + BSCScan tx hash | demo_script.md SCENE 4 | **PARTIAL** | `scripts/test_swap.py` exists separately | The swap functionality exists in `twak.py` and a separate `test_swap.py` script. The main agent loop does not invoke `twak.swap()` from within the cycle. |

---

## 3. CMC Data Feed

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| Bulk quotes endpoint | ARCHITECTURE.md §3, PLAN.md Phase 1 Task 1.2 | **YES** | `src/cmc_client.py:58–91` (`get_bulk_quotes`) | `GET /v2/cryptocurrency/quotes/latest` with bulk `id=` / `symbol=` params. |
| Fear & Greed index | ARCHITECTURE.md §3, PLAN.md Phase 1 Task 1.2 | **YES** | `src/cmc_client.py:93–106` (`get_fear_greed`) | `GET /v3/fear-and-greed/latest`. |
| DEX Trending | ARCHITECTURE.md §3, PLAN.md Phase 1 Task 1.4 | **YES** | `src/cmc_client.py:108–121` (`get_dex_trending`) | `GET /v1/dex/tokens/trending/list`. Gracefully returns `[]` on failure. |
| Rate limiting (semaphore) | ARCHITECTURE.md §3 | **YES** | `src/cmc_client.py:32` (`Semaphore(5)`) | Concurrency limited to 5 simultaneous requests. |
| Retry with backoff | ARCHITECTURE.md §3, PLAN.md Phase 1 Task 1.2 | **YES** | `src/cmc_client.py:42–55`, `src/utils.py:58–74` (`retry_async`) | Exponential backoff, 3 retries, 1.5x multiplier. |
| SQLite cache (5-min TTL) | ARCHITECTURE.md §3, PLAN.md Phase 1 Task 1.6 | **YES** | `src/cache.py:15` (`CACHE_TTL_SECONDS = 300`) | WAL-mode SQLite, separate `cmc_quotes`, `cmc_trending`, `cmc_fear_greed` tables. |

---

## 4. 149-Token Allowlist

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| 149-token allowlist hardcoded | ARCHITECTURE.md §4 Risk Manager, PLAN.md Phase 1 Task 1.1, SUBMISSION.md Rules Verification | **YES** | `src/config.py:57–107` (ALLOWLIST dict), verified count: **149** | 149 tokens present. Tokens sourced from pre-existing real tokens + competitor repo narrative baskets + PancakeSwap Extended List. |
| Allowlist enforced in signal | PLAN.md Task 1.1, SUBMISSION.md | **YES** | `src/signal.py:224` (`ALLOWLIST_TO_TOKEN_ADDRESS`), `src/decision.py:71` (`_split_across_basket` checks `if token in ALLOWLIST`) | `_split_across_basket` filters to only allowlisted tokens. |

---

## 5. SQLite Journaling

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| WAL-mode SQLite | ARCHITECTURE.md §6 | **YES** | `src/portfolio.py:27` (`PRAGMA journal_mode=WAL`) | `logs/cascade_fade.db` path. |
| `trades` table | ARCHITECTURE.md §6, PLAN.md Phase 4 Task 4.1–4.2 | **YES** | `src/portfolio.py:42–60` | Fields: ts, side, symbol, token_in/out, amount_in/out, price_in/out, slippage_pct, tx_hash, signal_snapshot, realized_pnl, portfolio_value, mode, status. |
| `positions` table | ARCHITECTURE.md §6 | **YES** | `src/portfolio.py:60–68` | Fields: symbol, entry_ts, entry_price, amount, tx_hash, stop_price, take_price, open. |
| `portfolio_snapshots` table | ARCHITECTURE.md §6 | **YES** | `src/portfolio.py:68–72` | Fields: ts, total_value, cash_value, positions_value, peak_value. |
| `cmc_quotes` cache table | ARCHITECTURE.md §6 | **YES** | `src/cache.py:44–49` | symbol, data_json, ts. |
| Duplicate schema definitions | — | **ISSUE** | `src/cache.py:51–84` vs `src/portfolio.py:35–84` | Both files define identical `trades`, `positions`, `portfolio_snapshots` tables. `cache.py`'s schema is unused; all writes go to `portfolio.py`'s schema. No functional corruption but dead code. |
| Optional on-chain hash anchor | ARCHITECTURE.md §6, PLAN.md Phase 4 Task 4.9 | **NOT IMPLEMENTED** | `src/log.py` — not present | Stretch goal. No `keccak256` hash anchor implemented. |

---

## 6. Portfolio Tracking

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| Track holdings (positions) | PLAN.md Phase 2 Task 2.5 | **YES** | `src/portfolio.py:75–96` (get_positions, add_position, close_position) | Open positions tracked with entry price, stop/take prices. |
| Track cash balance | PLAN.md Phase 2 Task 2.5 | **YES** | `src/portfolio.py:111–122` (update_cash, get_cash_balance, initialize_cash) | Snapshot-based. |
| Compute portfolio value + drawdown | PLAN.md Phase 4 Task 4.3–4.6 | **YES** | `src/portfolio.py:124–162` (compute_value) | Uses price_map; computes peak and drawdown_pct. |
| Stop/take prices set on entry | ARCHITECTURE.md §4 Risk Manager | **YES** | `src/portfolio.py:82–84` (stop_price = entry * 0.95, take_price = entry * 1.10) | Hardcoded at 5% stop / 10% take. |

---

## 7. Risk Guards

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| 25% drawdown hard stop | ARCHITECTURE.md §4 Risk Manager table, PLAN.md Phase 4 Task 4.3, SUBMISSION.md | **YES** | `src/risk.py:23–36` (`check_drawdown`) | `MAX_DRAWDOWN_PCT = 0.25` from config. Kills at `dd >= 0.25`. |
| $5 portfolio floor | ARCHITECTURE.md §4 Risk Manager table, PLAN.md Phase 4 Task 4.4 | **YES** | `src/risk.py:38–51` (`check_portfolio_floor`) | `PORTFOLIO_FLOOR_USD = 5.0`. Stops new trades below $5. |
| 10% max exposure per trade | ARCHITECTURE.md §4 Risk Manager table | **YES** | `src/risk.py:75–91` (`position_size`), `src/config.py:34` (`MAX_POSITION_PCT = 0.10`) | Max 10% of portfolio per position. |
| Max 2 concurrent positions | ARCHITECTURE.md §4 Risk Manager table | **YES** | `src/config.py:32` (`MAX_POSITIONS = 2`) | Configured, enforced in `pre_trade_check`. |
| 5% stop-loss, 10% take-profit | ARCHITECTURE.md §4 Risk Manager table | **YES** | `src/portfolio.py:82–84` (stop/take prices set on entry) | 5% stop, 10% TP. NOTE: actual exit triggered by these prices is not wired in the main loop — see **Issue #3**. |
| 48-hour max hold timeout | ARCHITECTURE.md §4 Risk Manager table | **NOT IMPLEMENTED** | — | No 48h max-hold enforcement in the code. `MAX_HOLD_HOURS = 48` is defined in `config.py:40` but never used. |
| 1% max slippage (QuoterV2 pre-check) | ARCHITECTURE.md §4 Risk Manager table, PLAN.md Phase 3 Task 3.4 | **YES** | `src/risk.py:107` (`pre_trade_check` rejects if slippage_pct > MAX_SLIPPAGE_PCT = 0.01) | Also QuoterV2 used in `src/quoter.py` to get actual slippage estimates. |
| Daily heartbeat trade ($5 BNB↔USDT) | ARCHITECTURE.md §4 Risk Manager table, PLAN.md Phase 4 Task 4.5, SUBMISSION.md | **YES** | `src/risk.py:53–73` (`check_heartbeat`), `src/risk.py:130–139` (`select_heartbeat_pair`) | Triggers after 22h with no trade, or at HEARTBEAT_HOUR_UTC (20:00). `select_heartbeat_pair` returns BNB→USDT if holding BNB, else USDT→BNB. |
| Heartbeat size $5 | ARCHITECTURE.md §4 Risk Manager table | **YES** | `src/config.py:37` (`HEARTBEAT_SIZE_USD = 5`) | Also floor in `position_size` at line 89. |
| Risk tests passing | SUBMISSION.md "Test Results" | **BROKEN** | `tests/test_risk.py` — **tests cannot run** | Test file imports `RiskManager` but the actual class is named `RiskGuard`. Tests fail immediately at import time. See **Critical Bug #2**. |

---

## 8. Demo Video Script

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| Demo script at `.kimchi/docs/demo_script.md` | This audit scope | **YES** | `.kimchi/docs/demo_script.md` | 3-minute script with 7 scenes: terminal launch, narrative scan, signal confidence, TWAK swap, risk guardrail demo, portfolio dashboard, closing + BSCScan. |
| SCENE 2: Narrative scan, regime, 5-bucket scores | demo_script.md | **YES** | `src/signal.py` outputs `global_scan` with bucket_scores | Full structure present. |
| SCENE 3: verdict STRONG_LONG, conviction, position size | demo_script.md | **YES** | `src/signal.py:173–175` | Verdict mapped to conviction threshold (60+ = STRONG_LONG). |
| SCENE 5: CIRCUIT BREAKER TRIPPED, sizing reduced | demo_script.md | **PARTIAL** | Circuit breaker logic exists in `risk.py` but heartbeat in decision.py references `risk_manager` which is not properly integrated — see **Issue #3** | The circuit_breaker concept is present but the heartbeat-triggered circuit-breaker reduction display in the demo is not wired. |
| SCENE 6: PnL, drawdown, win rate displayed | demo_script.md | **PARTIAL** | SQLite logging exists; display/terminal output for PnL summary is not explicitly implemented | `trade_logger.get_recent_trades()` exists but no periodic PnL summary printer. |
| Recording checklist present | demo_script.md | **YES** | `.kimchi/docs/demo_script.md` end of file | Checklist present. |

---

## 9. GitHub Repo

| Requirement | Source Doc | Implemented | Evidence (file:line) | Notes |
|---|---|---|---|---|
| Public GitHub repo | SUBMISSION.md Rules Verification, PLAN.md Phase 6 Task 6.7 | **YES** | Remote: `git@github.com:polytom868-pixel/cascade-fade-bnb-hack.git` | Repo exists and is public. |
| README, ARCHITECTURE, code, tests | SUBMISSION.md | **YES** | `README.md`, `ARCHITECTURE.md`, `src/`, `tests/` | All present. PLAN.md moved to `old/`. |
| Docs consistent with actual code | PLAN.md Phase 6 Task 6.1–6.3 | **PARTIAL** | `ARCHITECTURE.md` and `SUBMISSION.md` reference plan items that are now in `old/`; current top-level docs reflect simplified design | Docs are consistent with the simplified implementation. |

---

## Critical Issues Requiring Fixes

### Issue #1 — CRITICAL: TWAK swap execution is not wired into the main agent loop

**Files:** `src/decision.py`, `src/agent.py`

**Description:** `DecisionEngine.evaluate()` in `src/decision.py` generates buy/sell actions and updates the in-memory portfolio, but **never calls `self.twak.swap()`**. The `TWAKExecutor` is passed into `DecisionEngine.__init__()` and stored as `self.twak`, but `evaluate()` only calls `self.portfolio.add()` / `self.portfolio.remove()` and `log_trade()`. The actual TWAK swap subprocess is never invoked.

The `Agent` class (`src/agent.py`) calls `self.decision.run_cycle()` and uses the result only for logging elapsed time. The returned `summary` dict (which contains buy/sell actions from `decision.evaluate()`) is never used to trigger swaps.

**Evidence:**
- `src/decision.py:1–162` — `DecisionEngine.evaluate()` updates portfolio in-memory but has no `await self.twak.swap(...)` call anywhere.
- `src/decision.py:19–20` — `from src.risk import RiskGuard` unused import (also suspicious).
- `src/agent.py:93–101` — `run_cycle()` calls `decision.run_cycle()` but discards the `summary` actions.

**Impact:** The agent will log buy/sell decisions but never execute actual swaps on BSC. This is the core functionality of the trading agent and must be fixed.

**Suggested fix:** After `decision.evaluate()` returns actions with buys/sells, the `Agent.run_cycle()` or `DecisionEngine` must call `await self.twak.swap()` for each buy/sell action. The `scripts/test_swap.py` shows the correct call pattern that must be replicated in the main loop.

---

### Issue #2 — CRITICAL: Tests cannot run — `RiskManager` vs `RiskGuard` naming mismatch

**File:** `tests/test_risk.py:17`

**Description:** `test_risk.py` imports `from src.risk import RiskManager` but the actual class in `src/risk.py` is named `RiskGuard`. The test file defines its own `RiskManager` type hint at line 15 (`async def test_drawdown_kill(risk: RiskManager) -> None:`) but the import statement at line 17 attempts to import `RiskManager` from `src.risk`, which does not exist.

**Evidence:**
```
ImportError: cannot import name 'RiskManager' from 'src.risk'
  → tests/test_risk.py:17: from src.risk import RiskManager
  → src/risk.py defines: class RiskGuard:
```

All 5 test functions reference `RiskManager` (not `RiskGuard`). The tests cannot be collected at all.

**Impact:** The test suite is completely broken. All risk guard tests (drawdown kill, portfolio floor, position size, pre-trade checks, heartbeat) cannot be run. The submission claims "All risk tests passed" but they have never successfully run.

**Suggested fix:** Either rename `RiskGuard` to `RiskManager` in `src/risk.py`, or change the import in `tests/test_risk.py:17` to `from src.risk import RiskGuard` and update all 5 test functions' type hints to `risk: RiskGuard`.

---

### Issue #3 — MODERATE: `MIN_TRADE_SIZE_USD` referenced but not defined

**File:** `src/decision.py:142`

**Description:** The `DecisionEngine.evaluate()` method references `MIN_TRADE_SIZE_USD` at line 142 when rejecting trades that are too small:
```python
actions["rejections"].append((token, f"amt ${amount:.2f} < min ${MIN_TRADE_SIZE_USD}"))
```
However, `MIN_TRADE_SIZE_USD` is not defined anywhere in `decision.py` or imported from `config.py`. `config.py` defines `PORTFOLIO_FLOOR_USD = 5.0` and `HEARTBEAT_SIZE_USD = 5` but not `MIN_TRADE_SIZE_USD`.

**Evidence:** `src/decision.py:1–13` — no `MIN_TRADE_SIZE_USD` in imports; `grep "MIN_TRADE_SIZE_USD" src/config.py` returns nothing.

**Impact:** If this code path is hit (when `amount < PORTFOLIO_FLOOR_USD`), Python will raise `NameError: name 'MIN_TRADE_SIZE_USD' is not defined`, causing the decision cycle to crash.

**Suggested fix:** Replace `MIN_TRADE_SIZE_USD` with `PORTFOLIO_FLOOR_USD` (from `src/config`), which is the intended semantic equivalent ($5 minimum trade).

---

### Issue #4 — MODERATE: `SignalEngineClass` constructor signature incompatible with `Agent` initialization

**Files:** `src/signal.py:216`, `src/agent.py:60`

**Description:** `SignalEngineClass.__init__` in `src/signal.py:217` requires a `cmc_client: CMCClient` argument:
```python
def __init__(self, cmc_client: CMCClient):
```
However, `src/agent.py:60` instantiates it with no arguments:
```python
self.signal_engine = SignalEngineClass()
```

**Evidence:**
- `src/signal.py:217`: `def __init__(self, cmc_client: CMCClient):`
- `src/agent.py:60`: `self.signal_engine = SignalEngineClass()`

**Impact:** `Agent.setup()` will crash with `TypeError: SignalEngineClass.__init__() missing 1 required positional argument: 'cmc_client'` when `await agent.setup()` is called. The narrative signal engine will fail to initialize.

**Suggested fix:** Change `src/agent.py:60` to:
```python
self.signal_engine = SignalEngineClass(self.cmc)
```

---

### Issue #5 — MODERATE: `DecisionEngine.__init__` has wrong signature

**File:** `src/agent.py:63–74` vs `src/decision.py`

**Description:** `Agent` passes 9 arguments to `DecisionEngine.__init__()` at `src/agent.py:63–74`:
```python
self.decision = DecisionEngine(
    cmc_client=self.cmc,
    signal_engine=self.signal_engine,
    risk_manager=self.risk_manager,
    portfolio=self.portfolio,
    quoter=self.quoter,
    twak=self.twak,
    trade_logger=self.trade_logger,
    cache=self.cache,
    mode=self.mode,
)
```
But `DecisionEngine.__init__` in `src/decision.py:24` only accepts 3 arguments:
```python
def __init__(self, twak_client, portfolio: Portfolio, risk: RiskGuard):
```

**Evidence:** `src/agent.py:63–74` vs `src/decision.py:24` — 9 args passed, 3 expected.

**Impact:** Either `Agent.__init__` crashes with `TypeError` when creating `DecisionEngine`, or the arguments are passed in the wrong order, causing silent bugs (wrong object types stored as wrong attributes). The current code in `decision.py` sets `self.twak = twak_client` (first arg), `self.portfolio = portfolio` (second arg), `self.risk = risk` (third arg). With the 9-argument call from `agent.py`, the positional mapping would be completely wrong: `cmc_client` would be stored as `self.twak`, `signal_engine` as `self.portfolio`, etc.

**Suggested fix:** Update `DecisionEngine.__init__` to accept all 9 arguments that `Agent` passes, and wire them into the class (including using `cmc_client` to fetch prices for `twak.price()` calls at lines 41 and 66).

---

### Issue #6 — MODERATE: `RiskGuard.circuit_breaker` method does not exist

**File:** `src/decision.py:34`

**Description:** `DecisionEngine.evaluate()` calls `self.risk.circuit_breaker(...)` at line 34:
```python
dd_ok, dd_msg = self.risk.circuit_breaker(balances.get("usd_value", 0))
```
But `src/risk.py` defines `check_drawdown(...)` method, not `circuit_breaker(...)`. The `RiskGuard` class has `check_drawdown`, `check_portfolio_floor`, `check_heartbeat`, `position_size`, `pre_trade_check`, and `select_heartbeat_pair` — no `circuit_breaker` method.

**Evidence:**
- `src/decision.py:34`: `self.risk.circuit_breaker(...)`
- `src/risk.py:23–36`: `async def check_drawdown(self, value: dict[str, Any])`

**Impact:** Every call to `DecisionEngine.evaluate()` will crash with `AttributeError: 'RiskGuard' object has no attribute 'circuit_breaker'`.

**Suggested fix:** Replace `circuit_breaker` with `check_drawdown` and adapt the return-value unpacking:
```python
result = await self.risk.check_drawdown({"drawdown_pct": ...})
dd_ok = result["safe"]
dd_msg = f"drawdown {result['drawdown_pct']:.2%}"
```

---

### Issue #7 — MODERATE: 48-hour max hold timeout defined but not enforced

**File:** `src/config.py:40` (defines `MAX_HOLD_HOURS = 48`), `src/decision.py` (never used)

**Description:** `MAX_HOLD_HOURS = 48` is defined in `config.py` and documented in ARCHITECTURE.md §4 as a sell condition. However, neither `decision.py` nor `risk.py` uses this constant. There is no code that checks if a position has been held longer than 48 hours.

**Evidence:**
- `src/config.py:40`: `MAX_HOLD_HOURS = 48`
- `grep -r "MAX_HOLD_HOURS" src/` → only in config.py itself

**Impact:** Positions can be held indefinitely, violating the documented sell condition. If a buy fires and price stays range-bound, the position would never exit on time basis.

**Suggested fix:** Add a 48h check in `DecisionEngine.evaluate()` by querying `portfolio.get_positions()` and checking `entry_ts` against current time.

---

### Issue #8 — LOW: Dead code — duplicate schema in `cache.py`

**File:** `src/cache.py:51–84`

**Description:** `cache.py` defines a full SQLite schema (trades, positions, portfolio_snapshots tables) in `_init_schema()`, but this schema is never written to — all trade/position/snapshot writes go through `portfolio.py`'s `Portfolio` class which manages its own schema. The `Cache` class only has working methods for `cmc_quotes`, `cmc_trending`, and `cmc_fear_greed` tables.

**Impact:** No functional corruption, but `cache.py`'s `_init_schema()` runs at every `Cache` instantiation (WAL pragma + schema init), wasting I/O. If `cache.py` and `portfolio.py` are ever both initialized (which they are in `Agent.__init__`), they both try to `CREATE TABLE IF NOT EXISTS` the same schema — SQLite handles this gracefully but it's misleading.

**Suggested fix:** Remove the dead `trades`, `positions`, `portfolio_snapshots` table definitions from `cache.py:_init_schema()`. Keep only `cmc_quotes`, `cmc_trending`, `cmc_fear_greed`.

---

## Summary Table

| Requirement | Status | Notes |
|---|---|---|
| Narrative rotation signal engine | ✅ IMPLEMENTED | Full 5-bucket scoring, exhaustion, conviction decay |
| Regime detection | ✅ IMPLEMENTED | RISK_ON / TRANSITION / RISK_OFF |
| 5-bucket scoring | ✅ IMPLEMENTED | All 5 bucket functions present |
| Exhaustion scoring | ✅ IMPLEMENTED | `compute_exhaustion_score` with 4 penalty conditions |
| Conviction decay | ✅ IMPLEMENTED | 10% per stale day |
| TWAK swap execution | ❌ NOT WIRED | `TWAKExecutor` never called from decision loop |
| CMC data feed | ✅ IMPLEMENTED | Bulk quotes, Fear & Greed, DEX trending, cache |
| 149-token allowlist | ✅ IMPLEMENTED | Exactly 149 tokens; enforced in basket splitting |
| SQLite journaling | ✅ IMPLEMENTED | WAL mode, 4 tables, but dead schema in cache.py |
| Portfolio tracking | ✅ IMPLEMENTED | Positions, cash, value, drawdown |
| 25% drawdown stop | ✅ IMPLEMENTED | But test broken (Issue #2) |
| $5 portfolio floor | ✅ IMPLEMENTED | But test broken (Issue #2) |
| 10% max exposure | ✅ IMPLEMENTED | `MAX_POSITION_PCT = 0.10` |
| 5% stop-loss / 10% take-profit | ⚠️ PARTIAL | Prices set on entry but exit not wired in loop |
| 48-hour max hold | ❌ NOT IMPLEMENTED | Constant defined but not enforced |
| 1% max slippage | ✅ IMPLEMENTED | QuoterV2 + risk check |
| Daily heartbeat | ⚠️ PARTIAL | Logic exists but heartbeat action not wired to TWAK |
| Risk tests passing | ❌ BROKEN | Test imports wrong class name (Issue #2) |
| Demo script | ✅ PRESENT | 7-scene script ready |
| GitHub repo pushed | ✅ YES | `polytom868-pixel/cascade-fade-bnb-hack` |
| On-chain registration | ❓ UNKNOWN | Code exists but not verified executed |
| Demo video | ❓ UNKNOWN | Script exists; video status not verifiable |

---

*Report generated by kimchi review agent. Issues are ordered by severity (critical first).*