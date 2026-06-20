# Verification Report — CascadeFade Bug Fixes

## Test Output

```
DRAWDOWN KILL: 25.00% >= 25.00%
DRAWDOWN KILL: 30.00% >= 30.00%
FLOOR BREACH: 4.99 < 5.00 — stopping new entries
✅ test_drawdown_kill passed
✅ test_portfolio_floor passed
✅ test_position_size passed
✅ test_pre_trade_checks passed
✅ test_heartbeat passed

🎉 All risk tests passed!
```

**Result: ALL_PASS** — 5/5 tests passed.

## Lint Output

All files pass `ast.parse` validation:
- `src/decision.py` OK
- `src/agent.py` OK
- `src/portfolio.py` OK
- `src/config.py` OK
- `src/cache.py` OK
- `tests/test_risk.py` OK

## Fixes Applied

### CRITICAL #1: `tests/test_risk.py` — `RiskManager` -> `RiskGuard`
- Changed import: `from src.risk import RiskManager` -> `from src.risk import RiskGuard`
- Changed all `RiskManager` type annotations to `RiskGuard`
- Changed `pre_trade_check` call signatures to match actual API (positional args: `{"total": ..., "drawdown_pct": ...}, slippage_pct, held_count`)
- Changed `risk = RiskManager(portfolio)` -> `risk = RiskGuard(portfolio)`

### CRITICAL #2: TWAK swap wiring in `src/decision.py`
- `evaluate()` is now `async def`
- For each BUY action: calls `await self.twak.swap(amount, CASH_CURRENCY, token, slippage=0.5)` and captures `tx_hash`
- For each SELL action: calls `await self.twak.swap(units, position_token, CASH_CURRENCY, slippage=0.5)` and captures `tx_hash`
- `tx_hash` stored in action dict and passed to `log_trade()`
- Added `run_cycle()` method to `DecisionEngine` so `agent.py` can call it

### P1 #1: `MIN_TRADE_SIZE_USD` in `src/config.py`
- Added `MIN_TRADE_SIZE_USD = 5.0` adjacent to `HEARTBEAT_SIZE_USD`
- Imported `MIN_TRADE_SIZE_USD` and `MAX_HOLD_HOURS` in `decision.py`

### P1 #2: 48-hour max hold timeout in `src/decision.py`
- In SELL loop, before routing to narrative rebalance logic, checks `entry_ts` age
- Uses `datetime.datetime.now(datetime.timezone.utc).timestamp()` vs position entry timestamp
- If `age_hours >= MAX_HOLD_HOURS`, appends forced sell with `"reason": "48h_timeout"`

### P1 #3: Duplicate schema removed from `src/cache.py`
- Removed `trades`, `positions`, `portfolio_snapshots` tables and their indexes
- Kept only `cmc_quotes`, `cmc_trending`, `cmc_fear_greed` tables
- Schema now lives solely in `portfolio.py`

### P1 #4: Stop/take-profit exits in `src/agent.py`
- In `run_cycle()`, fetches current prices for all held symbols via TWAK
- Iterates `await self.portfolio.get_positions()` and checks `stop_price`/`take_price`
- If `current_price <= stop_price`: prepends `{"token": sym, "reason": "stop_loss", ...}` to forced sells
- If `current_price >= take_price`: prepends `{"token": sym, "reason": "take_profit", ...}` to forced sells
- Forced sells prepended to `summary["actions"]["sells"]` before returning

## Additional Changes (required for compile/run)

- **`src/portfolio.py`**: Added synchronous `positions` dict (`{}`) and `add()`/`remove()`/`get()` methods used by decision.py's `evaluate()` loop. Added `get_stop_price()` and `get_take_price()`. Added `sync_position_to_db()` / `remove_position_from_db()` for async persistence.
- **`src/agent.py`**: Fixed `DecisionEngine` constructor call to match actual `(twak_client, portfolio, risk)` signature. Fixed `run_cycle()` to fetch prices and pass `price_map`.

## Verdict

**ALL_PASS**
