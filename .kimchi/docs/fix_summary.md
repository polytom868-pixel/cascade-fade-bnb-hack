# CascadeFade — Critical Blocker Fixes Summary

**Date:** 2026-06-20
**Fixed by:** Reviewer Agent
**Tests:** All 5 risk tests pass (`python tests/test_risk.py`)

---

## Fixed Issues

### B-3: Buy trades never open positions in portfolio tracking
**File:** `src/decision.py` (line 202)

After a successful buy via `_execute_swap`, the position was logged to the trade journal but never recorded in the `positions` table. This meant stop-loss (5%) and take-profit (10%) could never fire because the entry price was never stored.

**Fix:** After `_execute_swap` returns in the buy loop, `add_position` is now called:
```python
if result.get("amount_out", 0) > 0:
    entry_price = quotes.get(cand.symbol, {}).get("price", 0.0)
    await self.portfolio.add_position(
        cand.symbol,
        entry_price=entry_price,
        amount=result["amount_out"],
        tx_hash=result.get("tx_hash", "UNKNOWN"),
    )
```

---

### B-4: Portfolio cash never updated after trades
**Files:** `src/portfolio.py`, `src/decision.py`

`compute_value()` always received the stale `initial_cash` value. After any swap, the cash balance must be updated so subsequent position sizing, drawdown checks, and portfolio value are accurate.

**Fix (portfolio.py):** Added `update_cash(amount_usd: float)` method that persists the current cash balance to the most recent `portfolio_snapshots` row.

**Fix (decision.py):** Each `_execute_swap` call now returns `{"cash_after": float}`. The caller passes this updated `cash` to the next `compute_value()` call. At cycle end, `update_cash` is called to persist the final balance. Cash update logic:
- BUY (BNB → token): `cash -= amount * price_BNB`
- SELL (token → BNB): `cash += amount_out * price_BNB`

---

### B-5: Wrong slippage baseline in QuoterV2
**File:** `src/quoter.py` (lines 104–137)

The previous formula used `ideal_out = amount_in` (equal-value assumption). This is only correct when tokens have identical USD values. For BNB (~$300) vs USDT (~$1), this produces incorrect slippage estimates.

**Fix:** Added optional `price_map: dict[str, dict[str, Any]] | None` parameter to `estimate_slippage_single`. When provided, slippage is computed using USD-equivalent ideal output:
```python
ideal_out_usd = amount_in * from_price  # USD value of what we're spending
ideal_out = ideal_out_usd / to_price     # expected output in to_token units
slippage = max(0.0, (ideal_out - amount_out) / ideal_out)
```
Also fixed PYTH decimals from 18 → 6 (PYTH on BSC uses 6 decimals).

---

### B-7 (H-7 in gap audit): `eth_utils` missing from requirements
**File:** `requirements.txt`

`src/utils.py` imports `from eth_utils import to_checksum_address` but `eth-utils` was not listed in `requirements.txt`, causing `ModuleNotFoundError` on startup.

**Fix:** Added `eth-utils>=4.0.0` to `requirements.txt`.

---

### B-5 (H-2 in gap audit): Cache class-level shared `_db` bug
**File:** `src/cache.py` (lines 16–18)

`_db: aiosqlite.Connection | None = None` was a class variable, meaning all `Cache` instances shared one database connection. If one instance closed its connection, all others broke.

**Fix:** Moved `_db` into `__init__` as an instance variable, and added `db_path` as an instance variable too:
```python
def __init__(self, db_path: str | None = None) -> None:
    self._db_path = db_path or str(DB_PATH)
    self._db: aiosqlite.Connection | None = None  # Instance variable, not class-level
```

---

### B-6 (H-1 in gap audit): Cache never read before fetching
**File:** `src/decision.py` (`_fetch_quotes`, line 217)

`_fetch_quotes()` always called `cmc.get_bulk_quotes()` directly, making the cache effectively dead code and wasting CMC API rate limits.

**Fix:** `_fetch_quotes()` now checks `cache.get_quote(sym)` for every token first. Only cache-missed tokens are fetched via CMC bulk API, then written back to cache.

---

### B-7 (M-7 in gap audit): Trade log shows `portfolio_value=0.0`
**File:** `src/decision.py` (`_execute_swap`, line 343)

`log_trade` was called with `portfolio_value=0.0` hardcoded, making the trade log useless for audit/reconstruction.

**Fix:** Before calling `log_trade`, `compute_value(price_map, cash)` is called to get the actual portfolio total, which is then passed as `portfolio_value`.

---

## Verification

All files pass `python3 -c "import ast; ast.parse(open(f).read())"`:
- `src/cache.py` ✅
- `src/portfolio.py` ✅
- `src/quoter.py` ✅
- `src/decision.py` ✅

All 5 risk tests pass:
```
✅ test_drawdown_kill passed
✅ test_portfolio_floor passed
✅ test_position_size passed
✅ test_pre_trade_checks passed
✅ test_heartbeat passed
🎉 All risk tests passed!
```