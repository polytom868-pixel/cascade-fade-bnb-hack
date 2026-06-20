# CascadeFade Security & Financial Risk Review

## 1. The 30-Second Verdict

**NO.** I would not let this touch real money.

This is a prototype with a catastrophic cash-accounting flaw at its core: the agent does not read on-chain balances. It tracks cash as an in-memory float, adjusts it with math based on assumed prices, and uses that fiction to make risk decisions. Combined with a `break`-in-loop bug that kills all candidate evaluation after the first denial, stale-price ghost positions, a 22h heartbeat with no persistence of execution time, and an `initial_cash` that silently overwrites portfolio state on every restart, this will silently accumulate tracking error until the risk checks are meaningless.

---

## 2. The Five Most Dangerous Lines

### Landmine 1 — `decision.py:226-231` — Cash goes permanently negative

```python
if from_sym.upper() == "BNB":
    bnb_price = price_map.get("BNB", {}).get("price", 0.0) or 300.0  # fallback ~$300
    cash_after = cash - (amount * bnb_price)
else:
    bnb_price = price_map.get("BNB", {}).get("price", 0.0) or 300.0
    cash_after = cash + (amount_out * bnb_price)
```

**How it loses money:** Cash is a Python float, not an on-chain read. After every swap, `cash` is manually adjusted by multiplying `amount` by a price from `price_map`. If the BNB price in `price_map` is stale (5-minute cache TTL) and BNB moves 10%, every cash update in that 5-minute window is wrong by 10%. Compounded over 3 cycles, cash can be $100 off a $1000 portfolio. Once cash goes negative, `position_size()` divides by a negative number (`cash / portfolio_value`) producing a negative size, which is then clamped by `min(max_by_pct, cash)` — but the damage to risk checks is already done. The drawdown check at `decision.py:96` uses this poisoned `value["total"]`.

**The 300.0 fallback:** When BNB price is unavailable, `or 300.0` kicks in. BNB can trade at $400 or $200. If the cache is cold and prices are missing, every cash update uses the wrong BNB price. If BNB is $400 and we spend 5 BNB, the code deducts `5 * 300 = $1500` from cash instead of $2000. Cash is under-deducted. Then `compute_value` sees too much cash and thinks the portfolio is healthier than it is. Risk checks pass when they should fail.

---

### Landmine 2 — `decision.py:168-171` — `break` kills all candidate evaluation

```python
for cand in candidates[:MAX_POSITIONS - len(held_symbols)]:
    pre = self.risk.pre_trade_check(value, slippage_map.get(cand.symbol, 1.0), len(held_symbols))
    if not pre["approved"]:
        summary["actions"].append(f"buy_{cand.symbol}_denied: {pre['reason']}")
        break  # ← BUG: exits loop after FIRST denied candidate
```

**How it loses money:** `find_candidates` returns candidates sorted by confidence. The first candidate might be denied because current slippage exceeds threshold. The `break` then exits the entire buy loop — zero subsequent candidates are evaluated. If the second candidate had valid slippage and high confidence, the agent misses it and either holds cash idle or, if `HEARTBEAT_SIZE_USD` conditions are met, fires a meaningless $5 heartbeat instead of deploying capital properly. This is a cascading opportunity cost that can leave the portfolio uninvested while risk limits are actually fine for later candidates.

---

### Landmine 3 — `decision.py:247-252` — Phantom position entry on swap failure

```python
result = await self._execute_swap("BNB", cand.symbol, size, slippage, quotes, f"signal: {cand.reason}", cash)
cash = result["cash_after"]

# B-3 FIX: Record the bought position so it can be tracked for stop-loss / take-profit
if result.get("amount_out", 0) > 0:
    entry_price = quotes.get(cand.symbol, {}).get("price", 0.0)
    await self.portfolio.add_position(
        cand.symbol,
        entry_price=entry_price,
        amount=result["amount_out"],
        tx_hash=result.get("tx_hash", "UNKNOWN"),
    )
```

**How it loses money:** The `add_position` is gated only on `amount_out > 0`, but `amount_out` is computed by the formula `amount * (p_in / p_out)` — a mathematical ideal, not the actual on-chain received amount. If the TWAK swap returned 0 tokens out due to a blockchain reversion, `amount_out` could still be non-zero from the ideal math, and `add_position` records a fake position. The agent now holds a symbol it doesn't actually own. The next cycle's sell logic will attempt to close a position with no on-chain backing.

Even worse: if `status == "failed"` in live mode, `tx_hash` is None or "UNKNOWN". The position is written to SQLite with `tx_hash="UNKNOWN"`. There is no reconciliation job. The agent will try to manage a position that may not exist on-chain.

---

### Landmine 4 — `decision.py:96-105` — Kill switch uses stale entry price as exit price

```python
if not dd_check["safe"]:
    logger.critical("Kill switch: closing ALL positions")
    for pos in positions:
        symbol = pos["symbol"]
        quote = quotes.get(symbol, {})
        price = quote.get("price", 0.0) or pos["entry_price"]  # ← stale fallback
        cash = await self._execute_sell(symbol, price, quotes, "drawdown_kill", cash)
```

**How it loses money:** When `quote` is empty (API failure, rate-limit, token not in response), `price` falls back to `pos["entry_price"]` — the price from when the position was opened. This is catastrophically wrong in a liquidation scenario. If BNB crashed 40% and the CMC API returned errors for that cycle, every position is closed at entry price with no actual loss crystallized. But the cash update in `_execute_sell` uses `price * amount`, so the portfolio's computed value will reflect a false PnL of 0 on a position that is deeply underwater. The peak tracking in `compute_value` never updates because no real price movement was recorded. The drawdown calculation becomes meaningless.

---

### Landmine 5 — `risk.py:58-63` — Position size floor forces $5 trades into empty portfolios

```python
def position_size(self, cash: float, portfolio_value: float) -> float:
    max_by_pct = portfolio_value * MAX_POSITION_PCT
    size = min(max_by_pct, cash)
    if cash >= HEARTBEAT_SIZE_USD:
        size = max(size, HEARTBEAT_SIZE_USD)  # ← floors at $5 even when cash is $5 and portfolio is $5
    return round(size, 2)
```

**How it loses money:** With a $5 portfolio and $5 cash, `max_by_pct = 0.10 * 5 = $0.50`, so `size = min(0.50, 5.0) = $0.50`. Then `cash >= HEARTBEAT_SIZE_USD` (5 >= 5) is true, so `size = max(0.50, 5.0) = $5.00`. The agent over-invests 900% of the intended portfolio-per-position limit. If 2 positions are opened at $5 each, total deployed is $10 on a $5 portfolio — 200% of portfolio value. The STOP_LOSS_PCT of 5% on a $5 position is $0.25, which may be less than gas costs, creating a guaranteed-net-loss scenario.

---

## 3. The Nightmare Scenario — June 22 Hour by Hour

**7:00 AM UTC — Agent starts, 2 positions from yesterday.**
Portfolio: $980. Cash ~$800. BNB=$300. All okay. Drawdown = 2%.

**8:30 AM UTC — BNB drops 8% to $276. Cache is cold (5 min TTL, last refresh was 8:26 AM).**
`compute_value` uses stale cached BNB price of $300 for cash accounting. Cash still shows $800. Total portfolio shown as $980 instead of actual $940. Drawdown shown as 4% instead of 6%.

**Cycle runs. Two sell signals fire for existing positions (stop-loss not hit, but signal says sell).**
`_execute_sell` calls `_execute_swap(token → BNB)`. BNB price from `price_map` is still $300 (stale). `cash_after = cash + (amount_out * 300)`. But actual BNB received was valued at $276. Cash is overcredited by ~$24 per sell. Cash now shows $848 but actual wallet received ~$824 in BNB-equivalent.

**Heartbeat fires at 20:00 UTC (HEARTBEAT_HOUR_UTC).**
No trades in prior 22 hours. `select_heartbeat_pair` returns `("USDT", "BNB")`. `_execute_swap("USDT", "BNB", 5.0, slippage, quotes)` runs. BNB price from `price_map` is **still** $300 (cache miss? API error? prices not refreshed since 8:26 AM).

`ideal_out = 5.0 * 300 / 300 = 5.0` — this is a unitless amount of BNB, not actual tokens. The ideal BNB amount is `5 USD / $300 = 0.0167 BNB`. The TWAK swap actually sends ~0.0171 BNB to the wallet (slight slippage in agent's favor). `amount_out = 0.0171` from quoter.

`cash_after = 848 + (0.0171 * 300) = 853.13`. Cash goes UP by $5.13 because the code credited the USD value of BNB received at the stale $300 price.

**Position is opened: symbol held with amount 0.0171 at entry price $300.**

**9:42 PM UTC — BNB drops another 12% overnight to $264.**
Portfolio shown as $940. Actual portfolio is ~$880. Drawdown shown as 6%. Threshold is 25%. All clear.

**June 23, 6:00 AM UTC — Agent restarts (crash, redeploy, whatever).**
`agent = Agent(initial_cash=1000.0)` — hardcoded in `main()`.

`initialize_cash(1000.0)` inserts a new snapshot with `cash_value=1000.0, total_value=1000.0`.

All prior tracked cash ($848) is **abandoned**. The agent now thinks it has $1000 cash. The 3 positions on-chain are real. The agent's portfolio state is schizophrenic: it knows about 3 positions from the DB but thinks it has $1000 cash when the actual wallet might have $880 total value including BNB.

**First cycle post-restart: risk checks run against `cash=$1000, positions_value=3_positions`.**
Drawdown = (peak - total) / peak. Peak is whatever was recorded before restart. If peak was $1000, new total might be $880, drawdown = 12%. Still under 25%. Agent continues trading.

**Agent decides to close 2 positions and buy 2 new ones.**
Cash accounting is now completely detached from reality. The 4th position is opened with `cash_after = cash - (size * bnb_price)`. Since cash is $1000 and BNB is $264, spending $100 (10% of portfolio) deducts $100. But the wallet might not have $100 of BNB available — the actual BNB balance was already partially deployed in the 3 positions from yesterday.

**By noon June 23: agent is trading against a phantom $1000 cash balance while actual wallet is down to $400. The 25% drawdown kill fires, but `compute_value` is using fake cash. It may never fire correctly.**

---

## 4. Missing Tests — What Must Be Tested But Isn't

1. **On-chain balance reconciliation on restart.** When the agent starts with `initial_cash=1000` but actual wallet has $800, the entire risk layer is running on false data. There is no test that the agent reads its actual on-chain wallet balance before beginning trading. None.

2. **CMC API failure mid-cycle.** `_fetch_quotes` silently fills missing tokens with `{"error": "no_data", "price": None}`. No test verifies that the decision engine handles a cycle where 30% of allowlist tokens return errors. What happens to positions for tokens with stale $0 prices? The sell logic would treat them as $0 and `compute_value` would undercount positions.

3. **Heartbeat pair when both BNB and max positions are held.** If `held_symbols = ["BNB", "USDT"]` (somehow) or if held_count = MAX_POSITIONS and BNB is one of them, `select_heartbeat_pair` could return a pair that is already held or conflicts with existing positions.

4. **TWAK swap reverts on-chain but returns success.** If the BSC transaction reverts (slippage exceeded, insufficient gas, token pause), TWAK might still return a tx hash or a partial success. No test covers the case where `status == "confirmed"` with a valid `tx_hash` but the on-chain state is unchanged.

5. **Position over-investment at small portfolios.** Test with a $10 portfolio: `position_size(cash=5, portfolio_value=5)` returns $5 (correct) but `position_size(cash=5, portfolio_value=6)` returns $5 (100% of portfolio instead of 10%). This is not tested.

6. **Stale price + sell interaction.** No test covers what happens when a position is held and the price data goes stale (returns error or $0). The `pnl_pct` would compute as `-1.0` (entry_price > 0, current_price = 0), triggering immediate stop-loss regardless of actual performance.

7. **Concurrent cycle safety.** No test for what happens if `run_cycle` is called twice concurrently (e.g., if the interval timer fires while the previous cycle is still running). SQLite WAL mode helps but there is no asyncio lock preventing double-spends.

---

## 5. The One Dealbreaker

**Cash is not read from the blockchain. The entire risk management layer is built on a float that the agent invents.**

`decision.py` passes `cash: float` through every function as if it were ground truth. `portfolio.compute_value()` reads from SQLite snapshots that are themselves written by `decision.py`'s cash math. There is zero interaction with `self.twak` to verify what the wallet actually holds.

In paper mode, this doesn't matter — the agent is playing with numbers. In live mode, the real wallet has a balance. TWAK can query it via `get_balance()`. The agent never calls it after setup. `Agent.setup()` calls `get_address()` but discards the balance. `risk_manager.position_size()` uses the invented `cash` float. `check_drawdown()` and `check_portfolio_floor()` use `compute_value()` which uses the invented cash.

Every single risk decision — whether to trade, how much to trade, whether to kill all positions — is made against data the agent made up.

This is the dealbreaker. Fix the cash accounting first: read on-chain balances before every cycle, reconcile the SQLite snapshots against the wallet after every swap, and eliminate the fallback `or 300.0` price assumption entirely. Until then, the risk manager is a safety theater.

---

## Summary Table

| File | Line(s) | Severity | Issue |
|---|---|---|---|
| `decision.py` | 226-231 | CRITICAL | Cash accounting via price math, $300 fallback, no on-chain read |
| `decision.py` | 168-171 | HIGH | `break` exits buy loop after first denied candidate, loses opportunities |
| `decision.py` | 247-252 | CRITICAL | Position added from ideal math, not on-chain receipt; no reconciliation |
| `decision.py` | 96-105 | HIGH | Kill switch falls back to stale entry price, false PnL on forced liquidation |
| `risk.py` | 58-63 | MEDIUM | Position size floor forces 900%+ over-investment at small portfolio values |
| `portfolio.py` | 133-150 | HIGH | `update_cash` uses unverified `amount_usd` with no on-chain sanity check |
| `agent.py` | 53 | HIGH | `initial_cash=1000.0` overwrites all prior state on every restart |
| `decision.py` | 215 | MEDIUM | `ideal_out_usd / to_price` produces unitless BNB amount, not token units |
| `signal.py` | 85-87 | MEDIUM | Stale $0 price → pnl_pct = -1.0 → instant stop-loss regardless of reality |
| `quoter.py` | 79 | LOW | `or amount_in` fallback when no price data means slippage = 0 — passes silently |