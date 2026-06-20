# Wave Plan A — Fix Planner (Senior)
**Scope: Crash bugs, startup failures, config issues, name collisions, fake addresses**
**Based on:** critique_judge.md (missing), VC_BRUTAL_REVIEW.md, critique_dev.md (missing)

---

## Ranked 10 Micro-Fixes

---

### Fix 1 — CRITICAL: `src/config.py:93,96-101`
**Bug:** Fake/incrementing BSC contract addresses for PYTH, RAYDIUM, BONK, WIF, FLOKI, PEPE, MEME, MAGA, AI, AGI, AGIX, FET, OCEAN. Sequence starts at `0x14f5...` and increments by 1 per token. Live swaps to these addresses will revert on-chain, burning gas.

**Fix strategy:** Replace all 10+ fabricated entries with real BSC contract addresses verified on BSCScan. Use CMC's official mapped addresses or query directly from BSC RPC via `w3.eth.contract(address).symbols()`.

**Score impact:** Execution credibility (+30 pts if live swap confirmed, -50 pts if judge sees fake addresses)

---

### Fix 2 — CRITICAL: `src/decision.py:176`
**Bug:** `break` exits the buy-evaluation loop immediately after the first candidate is denied by `pre_trade_check`. Second, third, and fourth candidates with valid slippage and high confidence are never evaluated. Results in idle cash or wrong-size heartbeat trades instead of capital deployment.

**Fix strategy:** Change `break` to `continue` so denied candidates are logged but remaining candidates are still evaluated. Add a counter to cap total evaluated candidates at `MAX_POSITIONS - len(held_symbols)`.

**Score impact:** Strategy correctness (+15 pts), directly affects PnL

---

### Fix 3 — CRITICAL: `src/agent.py:53`
**Bug:** `Agent.__init__` stores `self.initial_cash = initial_cash` (hardcoded 1000.0 in main). On every restart, `initialize_cash(1000.0)` inserts a new snapshot with `cash_value=1000.0`, abandoning all prior tracked cash. Real wallet may have $400. Agent trades against a phantom $1000 balance indefinitely.

**Fix strategy:** In `setup()`, read actual wallet balance via `await self.twak.get_balance()` and pass real cash to `initialize_cash()`. If the call fails, fall back to reading the last snapshot's `cash_value` from SQLite (via `portfolio.get_cash_balance()`), NOT `initial_cash`.

**Score impact:** Risk management correctness (+20 pts), prevents runaway drawdown

---

### Fix 4 — HIGH: `src/decision.py:323-326`
**Bug:** `cash_after` uses `or 300.0` hardcoded BNB price fallback. When `price_map["BNB"]["price"]` is stale or absent (API rate-limit, cache miss), every cash update in that window uses wrong BNB price. At BNB=$400, cash is under-deducted by 33% per buy. Compounded over 3 cycles, risk checks operate on values 10-30% off.

**Fix strategy:** Remove the `or 300.0` fallback. Instead, if BNB price is missing, skip the cash update entirely (leave `cash` unchanged) and log a warning. Or fetch a fresh BNB price via an emergency fallback RPC call.

**Score impact:** Risk management accuracy (+15 pts)

---

### Fix 5 — HIGH: `src/decision.py:247-252`
**Bug:** Position is added to SQLite from `result["amount_out"]` computed as `amount * (p_in / p_out)` — a theoretical USD-equivalent, NOT the actual on-chain received token amount. If TWAK returns a real tx hash but the actual output differs (slippage, fees, MEV), the position entry is phantom. Agent will attempt stop-loss/take-profit management on a position it doesn't fully own.

**Fix strategy:** In live mode, parse the actual `amount_out` from TWAK's JSON response (or query the wallet balance before/after via `get_balance`). In paper mode, use the QuoterV2 quote output as a stand-in. Store the source of `amount_out` (`"twak_actual"` vs `"quote_theoretical"`) in the position record for reconciliation.

**Score impact:** PnL tracking accuracy (+15 pts)

---

### Fix 6 — HIGH: `src/decision.py:102-105`
**Bug:** Kill switch `_execute_sell` falls back to `pos["entry_price"]` when `quote.get("price")` is None. In a liquidation scenario where CMC rate-limits or API fails, every position is closed at entry price — false PnL of 0 on deeply underwater positions. Peak tracking in `compute_value` never updates. Drawdown calculation is poisoned.

**Fix strategy:** When `quote` is empty, fetch price from an emergency fallback source (BSC RPC token contract `balanceOf` read + DEX price oracle, or TWAK quote endpoint). If all fallbacks fail, log the error and skip the forced sell — do not close at stale entry price silently.

**Score impact:** Risk management correctness (+15 pts), prevents false portfolio snapshots

---

### Fix 7 — HIGH: `src/risk.py:66-68`
**Bug:** `position_size` floors at `HEARTBEAT_SIZE_USD` ($5) whenever `cash >= HEARTBEAT_SIZE_USD`. With a $6 portfolio, 10% max = $0.60, but floor kicks in: `max(0.60, 5.0) = $5.00` — 83% of portfolio in a single position. Two positions = 166% deployed capital. Creates a guaranteed-net-loss scenario where gas costs exceed stop-loss recovery.

**Fix strategy:** Remove the unconditional `max(size, HEARTBEAT_SIZE_USD)` floor. Replace with: `size = max(size, HEARTBEAT_SIZE_USD) if (cash >= HEARTBEAT_SIZE_USD and portfolio_value >= HEARTBEAT_SIZE_USD * 5) else size`. Only enforce heartbeat floor when the portfolio is large enough to absorb it.

**Score impact:** Risk management correctness (+10 pts), prevents over-leverage at small portfolios

---

### Fix 8 — MEDIUM: `src/risk.py:55-58`
**Bug:** When `max_by_pct = portfolio_value * MAX_POSITION_PCT` is less than cash, `size = min(max_by_pct, cash)` is correct. But the subsequent `if cash >= HEARTBEAT_SIZE_USD: size = max(size, HEARTBEAT_SIZE_USD)` unconditionally raises size to $5 even when `max_by_pct = $0.50` and portfolio = $5. This is the same bug as Fix 7, just different trigger path.

**Fix strategy:** Coalesce Fix 7's logic here: enforce heartbeat floor only when `portfolio_value >= HEARTBEAT_SIZE_USD * 5` (portfolio can sustain 5x heartbeat-sized positions without over-leveraging).

**Score impact:** Risk management consistency (+5 pts)

---

### Fix 9 — MEDIUM: `tests/test_risk.py`
**Bug:** Five test functions use `async def test_foo(risk: RiskManager)` expecting a pytest fixture named `risk` to be injected automatically. pytest does not auto-inject function arguments. These tests fail under `pytest` and only pass when run as standalone scripts via `asyncio.run(run_all())`. The test suite is decorative — no CI validation.

**Fix strategy:** Add a `pytest.fixture` at module scope: `@pytest.fixture async def risk(): portfolio = Portfolio(); yield RiskManager(portfolio); await portfolio.close()`. Change all `async def test_foo(risk: ...)` to `async def test_foo()` and call the fixture inside each test. Run `pytest tests/test_risk.py -v` and confirm all 5 pass. Add `--tb=short` to CI.

**Score impact:** Code quality / judges' trust (+10 pts, proves shippable test suite)

---

### Fix 10 — MEDIUM: `src/quoter.py:79` (approximate)
**Bug:** `estimate_slippage_single` returns `amount_out` from `self.quoter.functions.quote(...)` but if the quoter call fails and there is a fallback `or amount_in`, slippage is computed as `(amount_in - amount_in) / amount_in = 0.0` — a 0% slippage estimate. This passes `pre_trade_check` silently, allowing trades that should be blocked. Affects tokens without price data in `price_map`.

**Fix strategy:** After the quoter call, if `amount_out` falls back to `amount_in` (unit mismatch: from_token == to_token), explicitly set `slippage_pct = 1.0` (100%, blocked by `MAX_SLIPPAGE_PCT`). Or better: validate that `from_addr != to_addr` before quoting and return slippage=1.0 if they match (name collision / self-swap guard).

**Score impact:** Execution safety (+10 pts), prevents blind swaps

---

## Summary Table

| Rank | File | Line | Category | Severity |
|------|------|------|----------|----------|
| 1 | config.py | 93,96-101 | Fake addresses | CRITICAL |
| 2 | decision.py | 176 | Early break | CRITICAL |
| 3 | agent.py | 53 | Restart cash overwrite | CRITICAL |
| 4 | decision.py | 323-326 | Hardcoded BNB fallback | HIGH |
| 5 | decision.py | 247-252 | Phantom position amount | HIGH |
| 6 | decision.py | 102-105 | Stale entry price kill | HIGH |
| 7 | risk.py | 66-68 | Heartbeat floor over-lever | HIGH |
| 8 | risk.py | 55-58 | Same as Fix 7 (coalesce) | MEDIUM |
| 9 | test_risk.py | (module) | Missing pytest fixtures | MEDIUM |
| 10 | quoter.py | ~79 | Silent 0% slippage fallback | MEDIUM |

**Estimated total score improvement:** +95-145 pts across execution credibility, risk management, strategy correctness, and code quality dimensions.