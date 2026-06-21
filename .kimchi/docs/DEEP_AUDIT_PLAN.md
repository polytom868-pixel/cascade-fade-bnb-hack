# Deep Audit Plan — CascadeFade Codebase

**Date**: 2026-06-20  
**Baseline LOC**: **2879** (src=2291, tests=125, scripts=422, root=41)  
**Pyright errors**: **24** across 10 files  
**jscpd clones**: **6** (36 duplicated lines, 1.57% duplication rate)  
**Baseline dry-run time**: 0.3s per cycle (no DB state on C1, 6.0s with TWAK failures on C1)  

---

## 1. CMC API Batch Request — Confirmed ✅

```bash
curl -s -H "X-CMC_PRO_API_KEY: <key>" \
  "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?symbol=BTC,ETH,BNB,CAKE"
```

**Result**: Status 0, 25 quotes returned (each symbol returns a **list** of coins).  
**Behavior**: `data["BTC"]` is a list, NOT a dict. Our client code correctly handles this with canonical selection via `min(cmc_rank)`.  
**Relevance**: We can fetch ALL 149 allowlist tokens in a single batch call instead of subsetting. Currently we only fetch narrative-basket subsets.

---

## 2. Full Pyright Error Inventory (24 errors)

| # | File | Line | Error | Severity |
|---|---|---|---|---|
| 1 | `scripts/register_agent.py` | 86 | `Expected class but received ...` | type |
| 2 | `scripts/register_agent.py` | 147 | Address literal vs `Address` type | type |
| 3 | `scripts/register_agent.py` | 170 | Address literal vs `Address` type | type |
| 4 | `scripts/register_agent.py` | 227 | `TxReceipt` missing `status` attr | type |
| 5 | `scripts/register_agent.py` | 228 | `TxReceipt` missing `blockNumber` attr | type |
| 6 | `scripts/test_signal.py` | 13 | `"SignalEngine"` unknown import (renamed) | dead-code |
| 7 | `src/agent.py` | 146 | `self.twak.price()` does not exist | **runtime crash** |
| 8 | `src/cache.py` | 21 | `aiosqlite.Connection.closed` does not exist | type |
| 9 | `src/decision.py` | 69 | `Expected 2 positional arguments` (likely `self.twak.price`) | type |
| 10 | `src/log.py` | 22 | `aiosqlite.Connection.closed` does not exist | type |
| 11 | `src/log.py` | 86 | `int \| None` → `int` return type | type |
| 12 | `src/log.py` | 110 | `int \| None` → `int` return type | type |
| 13 | `src/portfolio.py` | 85 | `executescript` on `None` (optional db) | type |
| 14 | `src/portfolio.py` | 86 | `commit` on `None` (optional db) | type |
| 15-18 | `src/quoter.py` | 95,182,195 | Web3 `Address` type mismatch (hex literal `str` vs `Address`) | type |
| 19-24 | *(remaining 4 errors omitted for brevity — see full `pyright` output)* |  |  |  |

---

## 3. jscpd Duplication Inventory (6 clones)

| # | Lines | Tokens | File A | File B | Pattern |
|---|---|---|---|---|---|
| 1 | 8 | 30 | `cache.py:58` | `cache.py:79` | Async fetch + cache miss handling |
| 2 | 7 | 34 | `cache.py:115` | `log.py:125` | Retry decorator wrapper |
| 3 | 7 | 34 | `cache.py:115` | `portfolio.py:331` | Retry decorator wrapper |
| 4 | 7 | 35 | `log.py:15` | `portfolio.py:16` | aiosqlite connection ping |
| 5 | 6 | 32 | `portfolio.py:114` | `portfolio.py:122` | Stop/take price computation |
| 6 | 7 | 29 | `portfolio.py:244` | `portfolio.py:314` | Position value summation |

**Additional duplications not found by jscpd** (shorter blocks):
- `stop_price = entry_price * (1 - 0.05)` and `take_price = entry_price * (1 + 0.10)` exist in both `portfolio.py` in-memory methods AND `portfolio.py` DB methods
- `self._db.close()` try/except pattern exists across `cache.py`, `log.py`, `portfolio.py`
- `datetime.now(timezone.utc).isoformat()` call site repeated 15+ times across files

---

## 4. Design Flaws & Anti-Patterns

### 4.1 In-memory + DB split (portfolio.py)
`Portfolio` maintains a dict `self.positions` AND a SQLite table `positions`. They are not synced automatically. The `add()` method writes to memory; `sync_position_to_db()` must be called manually. Decision engine never calls sync.

### 4.2 Cash is immutable (agent.py)
`initial_cash` hardcoded at $1000.00. After buys, `balances[CASH_CURRENCY]` never updates because it's regenerated from `initial_cash` every cycle. The `portfolio_snapshots` table has a `cash_value` column that could be used.

### 4.3 price_map construction is lazy (agent.py)
Currently `price_map` is built ONLY for held symbols. When basket tokens need prices for buys, they fallback to $1.00 (fiction). Should fetch ALL basket allowlist symbols at cycle start.

### 4.4 Sell logic is a dead-end (agent.py + decision.py)
`agent.py` collects `forced_sells` (stop/take-profit) but only prepends them to the summary. No `portfolio.close_position()` or `twak.swap()` is called. `decision.py` sell loop always calls `twak.swap()` even in paper mode.

### 4.5 signal.py vs `signal` stdlib
Renamed to `SignalEngineClass` but tests still import `SignalEngine`.

---

## 5. Proposed Task Decomposition (4 Agents, Zero Conflicts)

All 4 agents work on **disjoint file sets**. No two agents edit the same file.

### Agent A — Type Fortress (`quoter.py`, `register_agent.py`, `test_signal.py`)
**Scope**: Fix all Web3 type errors + dead import.  
**Files**: `src/quoter.py`, `scripts/register_agent.py`, `scripts/test_signal.py`  
**Strategy**: Use `Web3.to_checksum_address()` to cast hex literals → `ChecksumAddress`. Wrap `TxReceipt` in `cast(dict, receipt)` or access via dict indexing. Update `test_signal.py` import to `SignalEngineClass`.  
**Estimated delta**: -5 errors, -10 LOC (by removing casts).

### Agent B — DB Consul (`portfolio.py`, `cache.py`, `log.py`)
**Scope**: Dedup connection/retry patterns, fix optional-None errors, sync memory→DB.  
**Files**: `src/portfolio.py`, `src/cache.py`, `src/log.py`  
**Strategy**:
1. Extract `retry_async` from `cache.py` + `log.py` + `portfolio.py` into `utils.py` once.
2. Extract `_ensure_db()` connection helper into `utils.py`.
3. In `portfolio.py`, make `add()` also call `sync_position_to_db()`.
4. In `portfolio.py`, dedup `stop_price`/`take_price` into one private method.
**Estimated delta**: -36 duplicated lines, -25 LOC, -5 pyright errors.

### Agent C — Runtime Fixer (`agent.py`, `decision.py`)
**Scope**: Fix crash-on-cycle-2, cash tracking, sell execution, price_map completeness.  
**Files**: `src/agent.py`, `src/decision.py`  
**Strategy**:
1. `agent.py`: Build `price_map` from CMC batch fetch using ALL symbols (held + all baskets).
2. `agent.py`: Replace `self.initial_cash` with `await self.portfolio.get_cash_balance()`.
3. `agent.py`: Execute `forced_sells` by calling `portfolio.close_position()`.
4. `decision.py`: Add paper-mode guard around sell `twak.swap()`.
5. `decision.py`: Remove or fix `_heartbeat_buy` (it calls missing `self.twak.price()`).
**Estimated delta**: +40 lines (new execution logic) -15 lines (removing dead code) = net +25.

### Agent D — Pruner (`risk.py`, `config.py`, `src/utils.py`, `tests/test_risk.py`)
**Scope**: Dead code removal, import cleanup, unify helpers.  
**Files**: `src/risk.py`, `src/config.py`, `src/utils.py`, `tests/test_risk.py`  
**Strategy**:
1. `config.py`: Remove duplicate 14-fabricated-address block (already removed) + dedup similar address dicts.
2. `risk.py`: Fix `peak_value` access (likely references wrong object); remove unused aliases.
3. `utils.py`: Add extracted helpers from Agent B (`retry_async`, `_ensure_db`).
4. `tests/test_risk.py`: Verify no import regressions.
**Estimated delta**: -20 LOC.

**Conflict Matrix**:
```
Agent A: quoter.py, register_agent.py, test_signal.py
Agent B: portfolio.py, cache.py, log.py
Agent C: agent.py, decision.py
Agent D: risk.py, config.py, utils.py, test_risk.py
→ ZERO overlapping files. All 4 can run in parallel.
```

---

## 6. Baseline Microbenchmark Protocol

Before and after each phase, capture:

| Metric | Command | Baseline |
|---|---|---|
| Total LOC | `wc -l $(find src -name '*.py')` | 2291 |
| Type errors | `pyright --pythonversion 3.11 . \| grep -c 'error:'` | 24 |
| Clones | `npx jscpd --pattern "src/**/*.py"` | 36 dup lines |
| Dry-run C1 | `time python -m src.agent --mode paper --cash 1000 --cycles 1` | 0.3s |
| Dry-run C2 | Same (needs DB state) | N/A (dies on cycle 2) |
| Test pass | `python -m pytest tests/ -q` | 5/5 pass |

---

## 7. Evidence of Improvement Required

| Defect | Evidence | Impact |
|---|---|---|
| #B1 Crash on C2 | `pyright error: Cannot access attribute "price"` in agent.py:146 | HIGH — agent dies after first position |
| #B2 Cash never decrements | agent.py: `initial_cash=1000` passed every cycle | HIGH — overspends, wrong sizing |
| #B3 DB not synced | portfolio.py `add()` modifies memory, `sync_position_to_db()` never called by decision | HIGH — health check shows 0 holdings |
| #B4 Sell dead code | agent.py forced_sells only prepended to dict, no execution | MEDIUM — stop/take-profit never fires |
| #B5 Paper sell crash | decision.py always calls twak.swap() even in paper | MEDIUM — TWAK error every cycle |
| Duplication | jscpd: 36 lines duplicated across cache/log/portfolio | LOW — maintainability |
