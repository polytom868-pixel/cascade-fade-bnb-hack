# CascadeFade Strategy Quality Review

**Specialty:** Buy signal logic, confidence scoring, volume filter  
**Reviewer:** Senior Fix Planner  
**Date:** 2026-06-20

---

## Verdict: NEEDS_FIXES

The strategy signal layer suffers from **inverted incentives**, **missing volume awareness**, **naive edge estimation**, and **cascading opportunity-cost bugs** in the buy loop. The core thesis — "low-attention momentum fade" — is contradicted by the code that implements it. A 50 % weekly gainer receives maximum confidence, which is the exact opposite of buying calm before the crowd.

Below are the issues, ordered by severity (correctness first, then strategy fidelity).

---

## Issue 1 — Inverted confidence score rewards hype bags

**File:** `src/signal.py`  
**Lines:** 91–92

```python
confidence=min(abs(change_7d) / 20.0, 1.0),
```

**Problem:**  
A token up 50 % in 7 days gets confidence 1.0. The thesis is "buy BEFORE the crowd notices." A 50 % weekly mover is the definition of crowd attention. The ranking algorithm therefore preferentially buys the ripest retail bags — the exact hype the agent pretends to avoid.

**Correct behavior:**  
Confidence should be **highest in the 5–15 % weekly-change band** (genuine early drift, not yet viral) and **penalized >30 %** (obvious hype). The score should also incorporate a volume-attenuation factor so parabolic price + volume spikes score near zero.

**Suggested fix:**
```python
# Inverted-U confidence: reward modest drift, penalize extremes
raw = abs(change_7d)
if raw <= 5.0:
    drift_score = raw / 5.0 * 0.5          # 0→5 %  maps 0→0.5
elif raw <= 15.0:
    drift_score = 0.5 + (raw - 5.0) / 10.0 * 0.5  # 5→15 % maps 0.5→1.0
elif raw <= 30.0:
    drift_score = 1.0 - (raw - 15.0) / 15.0 * 0.5 # 15→30 % maps 1.0→0.5
else:
    drift_score = max(0.0, 0.5 - (raw - 30.0) / 20.0 * 0.5)

# Volume attention proxy (see Issue 2)
volume_score = 1.0 - min(volume_spike_ratio / 3.0, 1.0)

confidence = round(drift_score * volume_score, 4)
```

---

## Issue 2 — Zero volume filter; no attention proxy

**File:** `src/signal.py`  
**Lines:** 55–92 (`evaluate_buy`)

**Problem:**  
The only "attention" check is a binary `symbol in trending_top3` test. There is no volume-based filtering, no relative-volume ranking, no on-chain transfer-count proxy. A token can have 10× average volume (clear attention spike) and still pass the signal because it is not in the top-3 DEX trending list.

**Correct behavior:**  
The strategy thesis explicitly requires a **low-attention** state. Volume is the canonical on-chain attention proxy. The signal should reject tokens whose 24 h volume is >2–3× their 7-day average.

**Suggested fix:**
1. Extend `CMCClient.get_bulk_quotes` to also fetch `volume_24h` and `volume_change_24h` (CMC already returns these fields in the standard quote response).
2. In `evaluate_buy`, after the slippage check, add:
```python
vol_24h = quote.get("volume_24h", 0.0) or 0.0
vol_change_24h = quote.get("volume_change_24h", 0.0) or 0.0
if vol_change_24h > 200.0:  # 3× baseline spike
    return SignalState(symbol, "hold", f"volume spike {vol_change_24h:.0f}% — attention too high")
```
3. Cache the 7-day rolling volume average per token so the filter uses relative change, not an absolute threshold.

---

## Issue 3 — Naive edge expectation uses arithmetic mean of daily changes

**File:** `src/signal.py`  
**Lines:** 84–86

```python
expected_edge = max(change_7d / 7.0, change_24h / 24.0)  # naive daily drift estimate
if expected_edge < ROUND_TRIP_COST_PCT:
    return SignalState(symbol, "hold", f"expected edge {expected_edge:.4%} < cost {ROUND_TRIP_COST_PCT:.2%}")
```

**Problem:**  
`change_7d / 7.0` is not an "edge" — it is the arithmetic average of daily returns assuming linear price movement. Real price paths are convex; this estimate has zero predictive power. A token that went +20 % in 7 days then -18 % on day 8 still passes with `20/7 ≈ 2.86 %` "edge." The `ROUND_TRIP_COST_PCT = 0.006` threshold is therefore meaningless.

**Correct behavior:**  
Replace with a **momentum-quality** metric: the ratio of positive days to total days in the window, weighted by log-return magnitude. Or, simpler and sufficient for a hackathon: use the 24h change *relative to* the 7d change as a freshness proxy. If 24h is already >80 % of 7d, the move is front-loaded and edge is low.

**Suggested fix:**
```python
# Freshness-adjusted edge: reward gradual drift, punish front-loaded spikes
daily_7d = change_7d / 7.0
daily_24h = change_24h / 1.0
freshness = daily_24h / daily_7d if daily_7d != 0 else 0.0

# Expected edge = lower of the two dailyized rates, damped by freshness
expected_edge = min(abs(daily_7d), abs(daily_24h)) * (1.0 - abs(freshness - 1.0))
if expected_edge < ROUND_TRIP_COST_PCT:
    return SignalState(...)
```

---

## Issue 4 — `break` kills buy loop after first denied candidate

**File:** `src/decision.py`  
**Lines:** 168–171

```python
for cand in candidates[:MAX_POSITIONS - len(held_symbols)]:
    pre = self.risk.pre_trade_check(...)
    if not pre["approved"]:
        summary["actions"].append(f"buy_{cand.symbol}_denied: {pre['reason']}")
        break  # ← BUG
```

**Problem:**  
Candidates are sorted by confidence descending. The first candidate might be denied because its slippage exceeds threshold. The `break` exits the **entire** buy loop — zero subsequent candidates are evaluated. If candidate #2 had valid slippage and high confidence, the agent misses it and either holds cash idle or fires a meaningless heartbeat.

**Correct behavior:**  
Use `continue` so the loop evaluates all candidates and fills as many positions as risk allows.

**Suggested fix:**
```python
    if not pre["approved"]:
        summary["actions"].append(f"buy_{cand.symbol}_denied: {pre['reason']}")
        continue  # evaluate next candidate
```

---

## Issue 5 — Stale $0 price triggers instant false stop-loss

**File:** `src/signal.py`  
**Lines:** 101–103

```python
current_price = quote.get("price", 0.0) or 0.0
if current_price <= 0 or entry_price <= 0:
    return SignalState(symbol, "hold", "invalid prices")

pnl_pct = (current_price - entry_price) / entry_price
```

**Problem:**  
When CMC returns `"error": "no_data"` the quote dict contains `"price": None`. The `or 0.0` fallback sets `current_price = 0`. `pnl_pct` becomes `-1.0` ( -100 % ), which immediately triggers the `pnl_pct <= -STOP_LOSS_PCT` ( -5 % ) branch and liquidates a healthy position based on a stale API response.

**Correct behavior:**  
If price data is missing or stale, the sell evaluation must **hold** the position and log a warning, not compute a phantom -100 % PnL.

**Suggested fix:**
```python
current_price = quote.get("price")
if current_price is None or current_price <= 0:
    logger.warning("Stale price for %s — skipping sell evaluation", symbol)
    return SignalState(symbol, "hold", "stale price — no sell eval")
if entry_price <= 0:
    return SignalState(symbol, "hold", "invalid entry price")
```

---

## Issue 6 — Position size floor forces 900 % over-investment at small portfolio values

**File:** `src/risk.py`  
**Lines:** 58–63

```python
def position_size(self, cash: float, portfolio_value: float) -> float:
    max_by_pct = portfolio_value * MAX_POSITION_PCT
    size = min(max_by_pct, cash)
    if cash >= HEARTBEAT_SIZE_USD:
        size = max(size, HEARTBEAT_SIZE_USD)
    return round(size, 2)
```

**Problem:**  
With a $5 portfolio and $5 cash, `max_by_pct = 0.10 * 5 = $0.50`, so `size = $0.50`. Then `cash >= HEARTBEAT_SIZE_USD` (5 >= 5) is true, so `size = max(0.50, 5.0) = $5.00`. The agent over-invests 900 % of the intended per-position limit. Two such positions = $10 deployed on a $5 portfolio.

**Correct behavior:**  
The heartbeat floor should only apply to **heartbeat trades**, not to regular signal-driven buys. For signal buys, the 10 % cap must be absolute.

**Suggested fix:**
```python
def position_size(self, cash: float, portfolio_value: float, is_heartbeat: bool = False) -> float:
    max_by_pct = portfolio_value * MAX_POSITION_PCT
    size = min(max_by_pct, cash)
    if is_heartbeat and cash >= HEARTBEAT_SIZE_USD:
        size = max(size, HEARTBEAT_SIZE_USD)
    return round(size, 2)
```
Then pass `is_heartbeat=True` only from the heartbeat branch in `decision.py`.

---

## Issue 7 — Hardcoded `initial_cash` overwrites real portfolio state on every restart

**File:** `src/agent.py`  
**Line:** 53  
**File:** `src/decision.py`  **Lines:** 57–58, 102

**Problem:**  
`Agent.__init__` hardcodes `initial_cash: float = 1000.0`. `run_cycle` is called with this value every cycle. On restart, `portfolio.initialize_cash(1000.0)` inserts a fresh $1000 snapshot, abandoning all prior tracked cash. The agent then trades against a phantom $1000 while the real wallet may be at $400.

**Correct behavior:**  
On startup, read the **actual on-chain BNB + stablecoin balance** via `Quoter.get_balance()` / TWAK, convert to USD using the freshest CMC quote, and use that as the cash basis. Store it in SQLite once. On subsequent cycles, read from SQLite, not from the constructor parameter.

**Suggested fix:**
In `Agent.setup()`, after verifying connectivity:
```python
# Read actual wallet balances
bnb_bal = self.quoter.get_balance(wallet_addr, WBNB)
usdt_bal = self.quoter.get_balance(wallet_addr, ALLOWLIST["USDT"])
# ... other stables
bnb_price = (await self.cmc.get_bulk_quotes({"BNB": ""})).get("BNB", {}).get("price", 0.0)
actual_cash = bnb_bal * bnb_price + usdt_bal  # plus other stables

# Only initialize if SQLite is empty
existing = await self.portfolio.get_cash_balance()
if existing == 0.0:
    await self.portfolio.initialize_cash(actual_cash)
    logger.info("Initialized cash from on-chain: $%.2f", actual_cash)
else:
    logger.info("Resuming with tracked cash: $%.2f", existing)
```
Remove `initial_cash` from `run_cycle` signature; always read from `portfolio.get_cash_balance()`.

---

## Issue 8 — `find_candidates` returns candidates even when quote is stale/error

**File:** `src/signal.py`  **Lines:** 147–153

```python
for symbol, quote in quotes.items():
    if not quote or "error" in quote:
        continue
    buy = self.evaluate_buy(...)
    if buy.action == "buy":
        signals.append(buy)
```

**Problem:**  
This is actually correct (skips errors). However, the caller in `decision.py` later uses `quotes.get(cand.symbol, {})` to get the **entry price** for `add_position` (line 249). If the quote was stale by the time of execution (cached 5 min TTL, price moved), the entry price recorded in SQLite is wrong. Stop-loss and take-profit levels are then computed from a stale price.

**Correct behavior:**  
Re-fetch a fresh quote immediately before calling `add_position`, or at minimum use the price from the most recent successful CMC response within the same cycle.

**Suggested fix:**
Inside `decision.py` before `add_position`:
```python
# Re-read fresh quote for entry price
fresh_quote = quotes.get(cand.symbol, {})
entry_price = fresh_quote.get("price", 0.0)
if entry_price <= 0:
    logger.warning("No fresh price for %s — skipping position record", cand.symbol)
    continue
await self.portfolio.add_position(
    cand.symbol, entry_price=entry_price, amount=result["amount_out"], ...
)
```

---

## Issue 9 — Config allowlist contains 20+ fabricated contract addresses

**File:** `src/config.py`  **Lines:** 89–108

**Problem:**  
Addresses for PYTH, JUP, RAY, RAYDIUM, BONK, PENGU, WIF, FLOKI, PEPE, MEME, MAGA, AI, AGI, AGIX, FET, OCEAN are incrementing hex sequences (`0xD3c0A2...`, `0x0231f9...`, `0x15f6AC...`). These are not valid BSC contracts. Any swap routed to these addresses will revert and burn gas.

**Correct behavior:**  
Replace all fabricated addresses with verified BEP-20 contract addresses from BSCScan. For tokens not deployed on BSC, set `None` and skip them in `ALLOWLIST` iteration.

**Suggested fix:**
```python
# Verified BSC contract addresses only
ALLOWLIST = {
    "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "USDT": "0x55d398326f99059fF775485246999027B3197955",
    ...  # etc.
    # Tokens without verified BSC contracts must be omitted or set to None
}
```

---

## Summary of Required Changes

| File | Lines | Priority | Fix |
|---|---|---|---|
| `src/signal.py` | 91–92 | P0 | Invert confidence to reward 5–15 % drift, penalize >30 % |
| `src/signal.py` | 55–92 | P0 | Add volume spike filter (>200 % 24h volume change = reject) |
| `src/signal.py` | 84–86 | P1 | Replace naive `max(change_7d/7, change_24h/24)` edge estimate |
| `src/decision.py` | 168–171 | P0 | Change `break` to `continue` in buy loop |
| `src/signal.py` | 101–103 | P0 | Hold (not sell) when price is stale/missing |
| `src/risk.py` | 58–63 | P1 | Add `is_heartbeat` param; only floor heartbeat trades |
| `src/agent.py` | 53 | P0 | Read on-chain balance on start; do not overwrite with hardcoded $1000 |
| `src/decision.py` | 247–252 | P1 | Re-fetch fresh quote before `add_position` entry price |
| `src/config.py` | 89–108 | P0 | Replace all fabricated addresses with verified BSC contracts |

---

## Test Gaps

The following strategy-critical behaviors have **no tests**:

1. **Confidence score ordering** — no test verifies that a 50 % gainer scores lower than a 12 % gainer after the fix.
2. **Volume spike rejection** — no test simulates a token with +300 % volume change and asserts it is skipped.
3. **Stale-price sell gate** — no test injects `"price": None` and asserts the position is held.
4. **Buy loop continuity** — no test where candidate 1 is denied (high slippage) and candidate 2 is approved.
5. **Position size cap at small portfolios** — no test with $5 portfolio asserting size = $0.50 for signal buys.
6. **On-chain cash reconciliation on restart** — no test verifying that restart reads SQLite cash, not `initial_cash`.
7. **Heartbeat vs signal buy sizing** — no test distinguishing heartbeat $5 floor from signal 10 % cap.

All seven gaps must be filled before the fix can be considered complete.
