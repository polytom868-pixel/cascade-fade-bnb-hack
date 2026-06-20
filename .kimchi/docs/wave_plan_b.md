# Wave B — Financial Safety Micro-Fixes (Ranked)

**Scope:** Phantom positions, fake cash, drawdown bugs, wallet balance reads, position tracking.
**Source:** `critique_judge.md`, `VC_BRUTAL_REVIEW.md`, `critique_dev.md` + source verification.

---

## Fix 1
**File:** `src/decision.py:226-231`
**Bug:** Cash updated via `cash - (amount * bnb_price)` using hardcoded `$300` BNB fallback when price is stale or missing. All cash arithmetic is invented — never read from chain.
**Fix:** Call `await self.twak.get_balance("BNB")` after every swap to read the real wallet BNB balance, convert to USD using the latest quote, and set `cash_after` to that figure. Remove `or 300.0`.
**Score impact:** Correctness — the entire risk layer (drawdown kill, floor check, position sizing) is currently running on phantom cash. Fixing this makes all downstream risk decisions real.

---

## Fix 2
**File:** `src/decision.py:168-171`
**Bug:** `break` exits the buy loop after the **first** denied candidate. If the highest-confidence candidate is denied on slippage, zero subsequent (equally or more valid) candidates are evaluated, leaving cash idle.
**Fix:** Change `break` → `continue`.
```python
# BEFORE
if not pre["approved"]:
    summary["actions"].append(f"buy_{cand.symbol}_denied: {pre['reason']}")
    break

# AFTER
if not pre["approved"]:
    summary["actions"].append(f"buy_{cand.symbol}_denied: {pre['reason']}")
    continue
```
**Score impact:** Capital efficiency — the agent currently may skip all buy candidates due to one bad actor, wasting a full cycle.

---

## Fix 3
**File:** `src/decision.py:245-252`
**Bug:** `add_position` is called with `result["amount_out"]` which is the **theoretically computed** `amount * (p_in / p_out)`, not the actual tokens received on-chain. If the swap reverts or slips badly, the position entry is phantom.
**Fix:** In live mode, after TWAK returns, call `await self.twak.get_balance(cand.symbol)` to read the actual wallet balance for that token and record that as `amount`. In paper mode, use the TWAK quoter result only if a quote was actually confirmed.
**Score impact:** Position tracking accuracy — prevents phantom positions that would later trigger false PnL, stop-loss, and take-profit fires against non-existent holdings.

---

## Fix 4
**File:** `src/decision.py:95-105`
**Bug:** Kill switch (`not dd_check["safe"]`) falls back to `pos["entry_price"]` when `quote.get("price")` is missing. In a market crash where CMC API errors out, every forced close uses stale entry prices, producing false-zero PnL and preventing the drawdown tracker from correctly updating peak value.
**Fix:** If `quote` is empty or price is $0/None, use the current CMC BNB price as a conversion anchor (or log a warning and skip the forced close for that position). Never silently use `entry_price` as exit price.
```python
# BEFORE
price = quote.get("price", 0.0) or pos["entry_price"]

# AFTER
if not quote or quote.get("price", 0.0) <= 0:
    logger.warning("Kill switch: no price for %s, skipping close", symbol)
    continue
price = quote["price"]
```
**Score impact:** Drawdown kill correctness — ensures the kill switch actually crystallizes real PnL and resets peak tracking accurately.

---

## Fix 5
**File:** `src/risk.py:58-63`
**Bug:** `position_size(portfolio_value=5, cash=5)` → `max_by_pct = 0.50`, then `max(0.50, 5.0) = 5.0` — a 900% over-investment of portfolio-per-position budget. Any small-portfolio edge case results in guaranteed over-exposure.
**Fix:** The heartbeat floor must be gated against MAX_POSITION_PCT. Add a check: only enforce the `$5 floor` when it does not exceed `MAX_POSITION_PCT * portfolio_value`.
```python
# AFTER
max_by_pct = portfolio_value * MAX_POSITION_PCT
size = min(max_by_pct, cash)
# Enforce heartbeat floor only when it does not breach position size cap
if cash >= HEARTBEAT_SIZE_USD and size < HEARTBEAT_SIZE_USD and HEARTBEAT_SIZE_USD <= max_by_pct:
    size = HEARTBEAT_SIZE_USD
return round(size, 2)
```
**Score impact:** Risk management — prevents a single $5 heartbeat from consuming the entire portfolio of a small account.

---

## Fix 6
**File:** `src/agent.py:53` + `src/agent.py:149`
**Bug:** `Agent(mode=mode, initial_cash=1000.0)` in `main()` and `self.initial_cash = 1000.0` in `__init__` silently overwrite all prior portfolio state on every restart. Real wallet may hold $400; `initialize_cash(1000.0)` inserts a new snapshot claiming $1000.
**Fix:** On startup, call `await self.twak.get_balance("BNB")` and `await self.twak.get_balance("USDT")`, convert to USD using the live quote, and pass that real total as `initial_cash`. Only use the `$1000` default as an absolute last resort when on-chain reads fail.
```python
# In setup(), after TWAK address check:
try:
    bnb_bal = await self.twak.get_balance("BNB")
    bnb_usd = bnb_bal * (await self.cmc.get_bulk_quotes({"BNB": ""}))["BNB"]["price"]
    usdt_bal = await self.twak.get_balance("USDT")
    self.initial_cash = bnb_usd + usdt_bal
except Exception:
    logger.warning("Could not read wallet balance, using configured initial_cash=%.2f", self.initial_cash)
```
**Score impact:** Restart safety — eliminates the most catastrophic failure mode where a restart resets the agent's view of reality.

---

## Fix 7
**File:** `src/portfolio.py:133-150` (`update_cash`)
**Bug:** `update_cash` writes `amount_usd` directly to SQLite with no on-chain reconciliation. Since `amount_usd` flows from `_execute_swap`'s invented cash math, the snapshot table accumulates unverified figures.
**Fix:** After every swap, query actual wallet balances (as in Fix 3) and write the **reconciled** cash to `update_cash`, not the computed figure. Store `reconciled_cash` and `computed_cash` separately in the snapshot for debugging drift.
**Score impact:** Cash audit trail — allows post-mortem comparison of predicted vs actual balances, enabling detection of drift before it corrupts risk decisions.

---

## Fix 8
**File:** `src/signal.py:85-87`
**Bug:** `evaluate_sell` computes `pnl_pct = (current_price - entry_price) / entry_price`. If `current_price` is `$0` (CMC returns `price: None` for a stale token), `pnl_pct = -1.0` which immediately triggers stop-loss sell on every held position for that token.
**Fix:** Add a guard before PnL computation:
```python
# BEFORE (line 97-99)
current_price = quote.get("price", 0.0) or 0.0
if current_price <= 0 or entry_price <= 0:
    return SignalState(symbol, "hold", "invalid prices")
# PnL computation follows without re-check after stale lookup
pnl_pct = (current_price - entry_price) / entry_price

# AFTER
current_price = quote.get("price", 0.0) or 0.0
if current_price <= 0 or entry_price <= 0:
    return SignalState(symbol, "hold", "invalid prices")
# Guard: if price just went to 0 due to cache miss, treat as hold
if quote.get("error") == "no_data":
    logger.warning("Stale price for %s — skipping sell evaluation", symbol)
    return SignalState(symbol, "hold", "price data unavailable")
pnl_pct = (current_price - entry_price) / entry_price
```
**Score impact:** Sell signal accuracy — prevents cascade of accidental stop-loss fires when price data is temporarily unavailable.

---

## Fix 9
**File:** `src/decision.py:210-215`
**Bug:** `amount_out = amount * (p_in / p_out)` computes a **USD-equivalent** amount (e.g., BNB spent at $300 gives `amount_out` of USD value, not token units). Then `cash_after = cash + (amount_out * bnb_price)` is double-converting: it credits USD-value of received BNB at BNB price again. The `amount_out` from the formula IS already in USD terms — multiplying by `bnb_price` is wrong.
**Fix:** Compute the actual token amount received (`amount_out_tokens = amount_in * (p_in / p_out)` for BNB→token, or use QuoterV2 directly for the real quote). For cash, convert the received BNB tokens at the current BNB price only once:
```python
# For BNB→token (spend BNB): token amount_out = amount * (bnb_price / token_price)
# For token→BNB (receive BNB): bnb amount_out = amount * (token_price / bnb_price)
# Cash update: subtract/credit at the same price used to compute the amount
```
Separately, record the actual `amount_out_tokens` separately from the `amount_out_usd` used for slippage calculation.
**Score impact:** Cash arithmetic correctness — eliminates a systematic double-conversion that inflates cash after every sell cycle.

---

## Fix 10
**File:** `src/decision.py:213` (stale price in `else` branch)
**Bug:** In the `else` branch of `_execute_swap` (non-BNB source token, typically USDT→BNB heartbeat), `bnb_price = price_map.get("BNB", {}).get("price", 0.0) or 300.0` falls back to `$300` even though the `from_sym` is not BNB. If the heartbeat buys BNB and BNB's cached price is stale at `$300` while it's actually `$400`, the agent credits `amount_out * 300` instead of `amount_out * 400` — cash is under-credited by 25%.
**Fix:** Apply the same stale-price guard to both branches. If BNB price is unavailable or stale (e.g., cache TTL > 5 minutes), fail the trade with a warning rather than proceeding with a guessed price:
```python
bnb_quote = price_map.get("BNB", {})
bnb_price = bnb_quote.get("price", 0.0) or 0.0
if bnb_price <= 0:
    logger.error("Cannot execute swap: BNB price unavailable")
    return {"tx_hash": None, "status": "failed", "amount_out": 0.0, "cash_after": cash}
```
**Score impact:** Heartbeat reliability — prevents the agent's forced maintenance trade from running on a stale price assumption that corrupts cash accounting.

---

## Summary Table

| Rank | File | Line(s) | Bug | Dimension |
|------|------|---------|-----|-----------|
| 1 | decision.py | 226-231 | No on-chain balance read; `or 300.0` fallback | Correctness |
| 2 | decision.py | 168-171 | `break` kills all candidate evaluation | Capital efficiency |
| 3 | decision.py | 245-252 | Position added from theoretical amount, not real balance | Position tracking |
| 4 | decision.py | 95-105 | Kill switch uses stale entry price as exit price | Drawdown accuracy |
| 5 | risk.py | 58-63 | Heartbeat floor forces 900%+ over-investment at small portfolio | Risk management |
| 6 | agent.py | 53, 149 | Restart overwrites state with $1000 phantom cash | Restart safety |
| 7 | portfolio.py | 133-150 | `update_cash` writes unverified invented cash | Cash audit trail |
| 8 | signal.py | 85-87 | Stale $0 price triggers instant stop-loss sell | Sell signal accuracy |
| 9 | decision.py | 210-215 | Double-conversion in cash arithmetic (USD * price) | Cash arithmetic |
| 10 | decision.py | 213 | Stale BNB price in non-BNB source token branch | Heartbeat reliability |