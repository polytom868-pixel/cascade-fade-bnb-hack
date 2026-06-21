# CascadeFade — Algorithmic Logic Performance Audit

**File:** `.kimchi/docs/perf_audit_logic.md`
**Date:** 2026-06-21
**Review scope:** `src/signal.py`, `src/decision.py`, `src/agent.py`, `src/config.py`, `src/risk.py`, `src/cmc_client.py`, `src/portfolio.py`, `src/quoter.py`

---

## 1. Algorithmic Complexity

### 1.1 — O(n x m) Token-to-Narrative Reverse Lookup

**File:** `src/decision.py`, method `DecisionEngine.evaluate`, sell loop

**Location:** Lines ~77–83
```python
for position_token in list(self.portfolio.positions):
    token_narrative = None
    for narr, tokens in NARRATIVE_BASKETS.items():   # ← O(narratives)
        if position_token in tokens:                  # ← O(basket_size)
            token_narrative = narr
            break
```

**Issue:** Every held position triggers a full scan of all 10 narratives × up to 5 tokens = up to 50 string comparisons per position. With `MAX_POSITIONS = 2` this is negligible, but the pattern is fragile — a future increase to 5–10 positions or 20 narratives makes this O(n × m) where it matters.

**Fix:** Build a reverse-map once at startup:
```python
# At DecisionEngine.__init__ or module load time
TOKEN_TO_NARRATIVE: dict[str, str] = {
    token: narrative
    for narrative, tokens in NARRATIVE_BASKETS.items()
    for token in tokens
}
# Then in the loop:
token_narrative = TOKEN_TO_NARRATIVE.get(position_token)
```
One-time O(50) build; every cycle becomes O(1) lookup.

---

### 1.2 — Double-Iteration for Portfolio Weight Normalization

**File:** `src/signal.py`, `global_scan`

**Location:** Lines ~108–116
```python
qualified = {n: max(d["conviction"], 1) for n, d in ranked if d["conviction"] >= MIN_THRESHOLD}
sum_sq = sum(v ** 2 for v in qualified.values())     # ← pass 1: O(n)
weights = {n: round((qualified[n] ** 2 / sum_sq) * 100, 1)
           if n in qualified else 0.0
           for n, _ in ranked}                       # ← pass 2: O(n) again
```

**Issue:** Two full O(n) passes (where n = 10 narratives). Trivial given 10 items, but the pattern is unnecessary. Also note that the second pass iterates over ALL ranked items (10) while only computing the weight for items in `qualified`, so 7 iterations compute 0.0 unnecessarily each cycle.

**Fix:** Single-pass or pre-filter before computing `sum_sq`:
```python
qualified = {n: max(d["conviction"], 1) for n, d in ranked if d["conviction"] >= MIN_THRESHOLD}
if qualified:
    sum_sq = sum(v ** 2 for v in qualified.values())
    weights = {n: round((v ** 2 / sum_sq) * 100, 1) for n, v in qualified.items()}
weights.update({n: 0.0 for n, d in ranked if d["conviction"] < MIN_THRESHOLD})
```

---

### 1.3 — O(n) Narrative Score Computation Per Cycle

**File:** `src/signal.py`, `global_scan`

**Location:** Lines ~104–107
```python
for narrative, data in narrative_data.items():   # O(narratives)
    results[narrative] = compute_narrative_score(...)
```

**Issue:** `compute_narrative_score` calls `compute_exhaustion_score` twice per narrative — once explicitly (to embed in the return dict) and once inside `score_risk_adjustment`. With 10 narratives = 20 calls instead of 10.

**Fix:** Cache the result and pass it through the call chain:
```python
# In score_risk_adjustment, accept an optional pre-computed exhaustion score
def score_risk_adjustment(narrative: str, data: dict, exhaustion_score: int = None) -> ...:
    if exhaustion_score is None:
        exhaustion_score, _ = compute_exhaustion_score(narrative, data)
    ...

def compute_narrative_score(...) -> dict:
    exhaustion_score, ex_reasons = compute_exhaustion_score(narrative, data)
    r_score, r_reasons = score_risk_adjustment(narrative, data, exhaustion_score)
    ...
    return {"exhaustion_score": exhaustion_score, ...}   # reuse, don't recompute
```

---

## 2. Redundant Computation

### 2.1 — Duplicate CMC Bulk-Quote Calls Per Cycle

**File:** `src/agent.py` (`run_cycle`) and `src/signal.py` (`SignalEngineClass._fetch_narrative_data`)

**Call 1 — agent.py, line ~91:**
```python
quotes = await self.cmc.get_bulk_quotes({s: "" for s in symbols_needed})
# symbols_needed = held_symbols ∪ all_basket_tokens ∪ {RISK_CURRENCY, "BNB"}
# ~50+ symbols
```

**Call 2 — signal.py, `SignalEngineClass.evaluate` → `_fetch_narrative_data`, line ~170:**
```python
qs = await self.cmc.get_bulk_quotes(symbol_map)
# symbol_map = all unique tokens across NARRATIVE_BASKETS (~30 tokens)
```

**Issue:** Every 30-minute cycle makes two separate CMC bulk-quote API calls for largely overlapping token sets. With ~48 cycles/day, this burns ~96 API calls/day instead of 48 — effectively doubling API quota consumption. CMC free tier is 15K/month so not immediately fatal, but wasted headroom.

**Fix:** Unify into a single fetch in `agent.py` and pass the price map to `signal_engine.evaluate(price_map)`:
```python
# In agent.py run_cycle:
quotes = await self.cmc.get_bulk_quotes({s: "" for s in symbols_needed})
price_map = {s: q.get("price", 0.0) for s, q in quotes.items()}

# Pass to signal engine:
summary = await self.decision.run_cycle(cash, price_map)
# Signal engine uses price_map for its own narrative data aggregation
```
The `SignalEngineClass` should accept `price_map` rather than re-fetching.

---

### 2.2 — `compute_exhaustion_score` Called Twice Per Narrative

**File:** `src/signal.py`

**Location:** `compute_narrative_score` lines ~97–99
```python
exhaustion_score = compute_exhaustion_score(narrative, data)[0]   # call 1
...
return {
    ...
    "exhaustion_score": compute_exhaustion_score(narrative, data)[0],  # call 2 ← DUPLICATE
    ...
}
```

The first call result is used for `r_score` logic inside `score_risk_adjustment`; the return dict re-calls it again. With 10 narratives, 10 wasted calls per cycle.

**Fix:** Assign and reuse:
```python
exhaustion_score, ex_reasons = compute_exhaustion_score(narrative, data)
# pass exhaustion_score to score_risk_adjustment
# return {"exhaustion_score": exhaustion_score, ...}
```

---

### 2.3 — Hardcoded `detect_market_regime` Parameters

**File:** `src/signal.py`, `SignalEngineClass.evaluate`

**Location:** Line ~167
```python
regime, reason = detect_market_regime(bnb_dominance=45, fear_greed=50, mcap_change_7d=0.02)
```

**Issue:** Regime is always "TRANSITION" (the else branch: 45 is not >65, 50 is not <30). The `cmc.get_fear_greed()` method exists in `cmc_client.py` but is never called. BNB dominance is also never fetched. The regime multiplier logic (1.1x / 0.9x / 0.7x) is completely dead code — every cycle uses `regime_mult = 0.9`.

**Fix:** Fetch real data:
```python
fear_greed_data = await self.cmc.get_fear_greed()
fear_greed = fear_greed_data.get("value", 50) if fear_greed_data else 50
# BNB dominance: compute from market cap of BNB vs total crypto market cap
# or fetch from CMC's global metrics endpoint
regime, reason = detect_market_regime(bnb_dominance=bnb_dom, fear_greed=fear_greed, mcap_change_7d=mcap_chg)
```

---

### 2.4 — `stop_loss` / `take_profit` Duplicated Between `config.py` and `portfolio.py`

**File:** `src/config.py` lines ~44–46 and `src/portfolio.py` line ~18

```python
# config.py
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.05"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.10"))

# portfolio.py
STOP_LOSS_PCT = 0.05   # ← hardcoded, no env support
TAKE_PROFIT_PCT = 0.10
```

**Issue:** If a trader changes `STOP_LOSS_PCT` via env var, `_compute_stop_take` in `portfolio.py` ignores it. The portfolio module should import from `config.py`.

**Fix:** Delete the local constants in `portfolio.py` and add:
```python
from src.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT
```

---

## 3. Logic Limitations (Strategy Underperformance vs. Competitors)

### 3.1 — Signal Data Is Entirely Fabricated

**File:** `src/signal.py`, `SignalEngineClass._fetch_narrative_data`

**Location:** Lines ~153–166
```python
data[narrative] = {
    "basket_return_7d_pct": mcap_change / 100 if mcap_change else 0,  # wrong (see 3.2)
    "volume_change_7d_pct": vol_change / max(avg_price, 1) * 100,      # BUG: vol_change = avg_price
    "relative_strength_vs_bnb_7d": 1.0,        # ← hardcoded, no real data
    "drawdown_from_30d_high_pct": 0.15,         # ← hardcoded placeholder
    "rsi_14": 50,                               # ← hardcoded placeholder
    "liquidity_usd": 10_000_000,                # ← hardcoded placeholder
    "spread_pct": 0.5,                          # ← hardcoded placeholder
    "social_volume_24h": 0,                     # ← hardcoded (Kaito never called)
    "trending_rank_avg": 50,                    # ← hardcoded (CMC trending never called)
    "volatility_30d": 0.5,                      # ← hardcoded placeholder
}
```

**Impact:** Every cycle, all 10 narrative scores are computed using fabricated data. This means:
- The "best narrative" is selected by a deterministic algorithm on noise.
- `score_momentum` always gets `relative_strength_vs_bnb_7d = 1.0` → never triggers the +35 or +20 momentum bonuses.
- `score_attention` always gets `trending_rank_avg = 50` → never triggers any attention bonus.
- `score_fundamental` checks fields (`github_commits_7d`, `holder_growth_7d_pct`, etc.) that are NEVER populated → AI Tokens and Meme narratives always score their `else: score += 10` baseline only.
- The `global_scan` ranking is effectively random.

**Competitor gap:** Real competitors fetch real social volume (via LunarCrush or Kaito), real DEX trending, real holder growth. The "fade the hype" signal requires knowing what IS hype — the current implementation cannot detect hype because `trending_rank_avg` is hardcoded at 50 (never trending) and `social_volume_24h` is 0 (never social).

---

### 3.2 — Bug: `volume_change_7d_pct` Uses Price, Not Volume

**File:** `src/signal.py`, `SignalEngineClass._fetch_narrative_data`

**Location:** Lines ~153–162
```python
avg_price = sum(b.get("price", 0) for b in basket_data) / max(len(basket_data), 1)
vol_change = max((b.get("volume_24h", 0) for b in basket_data), default=0)   # ← BUG: max of prices!
...
"volume_change_7d_pct": vol_change / max(avg_price, 1) * 100,                # ← nonsense
```

**Issue:** `max(...)` on generator of `volume_24h` values returns the maximum volume. But the variable name `vol_change` and the context suggest the author intended something different. The final expression `vol_change / avg_price * 100` treats volume as if it were price, producing meaningless percentages. Additionally, `percent_change_24h` from CMC quotes is available and directly represents price change — the code ignores it.

**Fix:**
```python
# Correct: use percent_change_24h as the basket return proxy
mcap_change = statistics.mean((b.get("percent_change_24h", 0) for b in basket_data))

# For volume change — use volume_24h from CMC, compare to prior day (requires caching)
# Or simplify: use percent_change_24h of the median-cap token in the basket as volume proxy
volume_change_pct = statistics.mean((b.get("volume_24h", 0) / max(prev_volumes.get(t, 1), 1) - 1
                                     for t, b in zip(tokens, basket_data)), default=0)
```

---

### 3.3 — Trending Dex Detection Never Implemented

**File:** `src/signal.py` and `src/agent.py`

**Issue:** The entire "fade the hype" sell signal — `token enters top-3 CMC DEX trending → force sell` — is un-implemented. `cmc_client.py` has `get_dex_trending()` which fetches the data, but:
- `agent.py` never calls `get_dex_trending()`.
- `signal.py` `score_attention` uses hardcoded `trending_rank_avg = 50` instead of real trending ranks.
- The sell logic in `decision.py` has no check for "token entered trending".

**Impact:** The "fade" half of "low-attention momentum fade" cannot work. A token can go parabolic on hype and the agent will keep holding it indefinitely (until 48h timeout or stop-loss).

---

### 3.4 — Fear & Greed Index Never Fetched

**File:** `src/signal.py`, `SignalEngineClass.evaluate`

The `cmc.get_fear_greed()` method exists in `cmc_client.py` but is never called anywhere. The buy rule requires "Global fear & greed not 'Extreme Fear'" but there is no mechanism to evaluate it. `fear_greed` is hardcoded to 50 in `detect_market_regime`.

---

### 3.5 — Narrative Token Overlap (COMP, PENDLE, CAKE in 7, 6, 3 Narratives)

**File:** `src/config.py`, `NARRATIVE_BASKETS`

```
COMP    → AI Tokens, AI Agents, RWA, DePIN, Privacy, DeFi Blue, BNB Chain  (7 narratives)
PENDLE  → AI Tokens, AI Agents, RWA, DePIN, DeFi Blue, Gaming/NFT           (6 narratives)
CAKE    → RWA, DePIN, Privacy, DeFi Blue, Gaming/NFT, BNB Chain             (6 narratives)
```

**Impact:** When the top narrative is "DeFi Blue", the buy basket includes AAVE, UNI, CAKE, COMP, PENDLE. But CAKE, COMP, and PENDLE also appear in other narratives. If the agent buys AAVE + UNI + CAKE + COMP + PENDLE and then "AI Tokens" becomes top narrative, it needs to sell COMP and PENDLE (which overlap) — creating a double-count problem in exposure sizing. With 2 max positions and 5-token baskets, the agent over-exposes to overlap tokens.

---

### 3.6 — `NARRATIVE_BASKETS["RWA"]` Contains Stablecoins

**File:** `src/config.py`
```python
"RWA": ["USDC", "FDUSD", "PENDLE", "COMP", "CAKE"],
```

USDC and FDUSD are stablecoins with ~$1 prices. Swapping into them via PancakeSwap makes no sense — they are the quote currency (USDT on BSC, but the config uses a BEP-20 USDC address). This basket will produce a near-zero output in any swap.

---

### 3.7 — Conviction History Gap Problem

**File:** `src/signal.py`, `compute_narrative_score`

**Location:** Lines ~88–91
```python
if conviction_history is not None and narrative in conviction_history:
    days_stale = day - conviction_history[narrative].get("last_day", day)
    if days_stale > 1:
        adjusted = int(adjusted * ((1 - CONVICTION_DECAY_RATE) ** days_stale))
```

**Issue:** If narrative "Meme" was top for 3 days (conviction 75), then the market rotates away and "Meme" disappears from `narrative_data` for 4 cycles, then re-emerges — the conviction history entry is orphaned. When it re-enters, `days_stale = day - last_day` can be very large (e.g., `day=20 - last_day=3 = 17`), applying a `0.9^17 ≈ 16%` decay even though the agent was not wrong — it just wasn't tracking that narrative.

**Fix:** Add a staleness cap:
```python
MAX_DECAY_DAYS = 7
days_stale = min(day - conviction_history[narrative].get("last_day", day), MAX_DECAY_DAYS)
```

---

### 3.8 — Risk `circuit_breaker` Checks Exposure Ratio Against Drawdown Threshold

**File:** `src/risk.py`, `RiskGuard.circuit_breaker`

**Location:** Lines ~53–60
```python
async def circuit_breaker(self, portfolio_value: float) -> tuple[bool, str]:
    peak_value = getattr(self.portfolio, "peak_value", portfolio_value)
    drawdown_pct = max(0.0, (peak_value - portfolio_value) / peak_value) if peak_value > 0 else 0.0
    result = await self.check_drawdown({"drawdown_pct": drawdown_pct})
    # check_drawdown: safe if drawdown_pct < MAX_DRAWDOWN_PCT (0.25)
```

**Issue:** The circuit breaker name and docstring describe it as a "drawdown kill". The implementation actually checks drawdown correctly. However, the `exposure_check` method (a different function in the same class) uses `MAX_EXPOSURE_RATIO = 0.90` internally and is not exposed as a constant — making it hard to tune. No issue here, just noting the asymmetry.

---

### 3.9 — `pre_trade_check` Signature Mismatch in decision.py

**File:** `src/risk.py`, `RiskGuard.pre_trade_check`

**Method signature:**
```python
def pre_trade_check(
    self,
    value: dict[str, Any],      # expects drawdown_pct, total
    slippage_pct: float,         # ← named slippage_pct
    held_count: int,             # ← named held_count
) -> dict[str, Any]:
```

**Call in decision.py, line ~118:**
```python
buy_ok, buy_msg = self.risk.pre_trade_check(
    {"total": balances.get("total_value", 0), "drawdown_pct": 0},  # value dict
    amount,        # ← passed as slippage_pct (but is trade amount in USD)
    0,             # ← passed as held_count (but is drawdown_pct=0)
)
```

**Issue:** The 2nd and 3rd positional arguments are misnamed at the call site. `amount` (a USD dollar amount, e.g. 50.0) is passed as `slippage_pct`. `0` is passed as `held_count`. The slippage check `slippage_pct > MAX_SLIPPAGE_PCT (0.01)` will always pass (50.0 > 0.01 is False — it's a number comparison, not a percentage check). The held_count check will also always pass because `0 >= MAX_POSITIONS` is False.

This means the pre-trade risk check's slippage and position-count guards are completely bypassed for BUY orders. SELL orders use a different call pattern that passes `slippage_pct=0`, which also bypasses both checks.

---

## 4. Concrete Optimizations

### 4.1 — Eliminate Duplicate CMC API Calls

| Where | What | Change |
|---|---|---|
| `agent.py:run_cycle` | Fetches ~50 symbols | Keep this as the single source of truth |
| `signal.py:SignalEngineClass.evaluate` | Re-fetches ~30 basket symbols | Accept `price_map` as argument; drop the internal fetch |
| `agent.py:run_cycle` | Pass `price_map` to `decision.run_cycle(cash, price_map)` | → `signal_engine.evaluate(price_map)` |

**Result:** 1 API call per cycle instead of 2. ~50% reduction in API quota usage.

---

### 4.2 — Build Token→Narrative Reverse Map at Startup

| Where | Change |
|---|---|
| `src/decision.py` | Add at class/module level: `TOKEN_TO_NARRATIVE = {token: narr for narr, tokens in NARRATIVE_BASKETS.items() for token in tokens}` |
| `decision.py:evaluate` sell loop | Replace `for narr, tokens in NARRATIVE_BASKETS.items(): if token in tokens` with `token_narrative = TOKEN_TO_NARRATIVE.get(token)` |

**Result:** O(1) lookup per held token instead of O(narratives × basket_size). Eliminates ~20 string comparisons per cycle.

---

### 4.3 — Cache `compute_exhaustion_score` Per Narrative Per Cycle

| Where | Change |
|---|---|
| `src/signal.py:compute_narrative_score` | Call `compute_exhaustion_score` once, pass result to `score_risk_adjustment`, reuse in return dict |
| `src/signal.py:score_risk_adjustment` | Accept `exhaustion_score: int` as optional arg; skip recompute if provided |

**Result:** 10 fewer function calls per cycle.

---

### 4.4 — Fetch Real Market Regime Data

| Where | Change |
|---|---|
| `signal.py:SignalEngineClass.evaluate` | `fear_greed_data = await self.cmc.get_fear_greed()`; `fear_greed = fear_greed_data.get("value", 50)` |
| `signal.py:SignalEngineClass.evaluate` | Compute `bnb_dominance` from BTC vs total mcap from CMC quotes |
| `signal.py:detect_market_regime` | Accept actual values instead of hardcoded 45/50/0.02 |

**Result:** Regime detection becomes functional. "RISK_ON" and "RISK_OFF" regimes become reachable, enabling the 1.1x and 0.7x conviction caps.

---

### 4.5 — Implement Trending Dex Detection

| Where | Change |
|---|---|
| `agent.py:run_cycle` | `trending = await self.cmc.get_dex_trending()` → top 3 symbols |
| `decision.py:evaluate` | In sell loop: check `if position_token in trending[:3]` → add to forced sells |

**Result:** The "fade the hype" sell signal becomes functional.

---

### 4.6 — Populate Real Data in `_fetch_narrative_data`

| Field | Current | Needed |
|---|---|---|
| `volume_change_7d_pct` | Buggy `max(volume_24h) / avg_price * 100` | Track `volume_24h` delta vs prior cycle via `cache.py` |
| `relative_strength_vs_bnb_7d` | Hardcoded `1.0` | Compute `token_7d_return / bnb_7d_return` from CMC `percent_change_7d` |
| `drawdown_from_30d_high_pct` | Hardcoded `0.15` | Requires 30d high tracking in `cache.py` (non-trivial to add) |
| `rsi_14` | Hardcoded `50` | Requires RSI computation over price history |
| `liquidity_usd` | Hardcoded `10_000_000` | Requires CMC `volume_24h` × price as proxy, or DexScreener API |
| `social_volume_24h` | Hardcoded `0` | Requires Kaito AI API (not free) or LunarCrush API |
| `trending_rank_avg` | Hardcoded `50` | Requires `cmc.get_dex_trending()` result |

**Short-term fix (no new APIs):** Use `percent_change_7d` from CMC quotes for `relative_strength_vs_bnb_7d` and `basket_return_7d_pct`; use `volume_24h` delta for `volume_change_7d_pct`. All data is available in the existing CMC quote response.

---

### 4.7 — Fix `pre_trade_check` Call in decision.py

| Where | Change |
|---|---|
| `decision.py:evaluate` | Change `self.risk.pre_trade_check({"total": ..., "drawdown_pct": 0}, amount, 0)` to `self.risk.pre_trade_check({"total": ..., "drawdown_pct": drawdown}, MAX_SLIPPAGE_PCT, len(self.portfolio.positions))` |

Or better: refactor `pre_trade_check` to accept named parameters for clarity:
```python
def pre_trade_check(
    self,
    total_value: float,
    drawdown_pct: float,
    held_count: int,
    slippage_pct: float,
) -> dict[str, Any]:
```

---

### 4.8 — Cap Conviction Decay Staleness

| Where | Change |
|---|---|
| `signal.py:compute_narrative_score` | After computing `days_stale`, add `days_stale = min(days_stale, 7)` before applying decay |

**Result:** Narrative conviction cannot decay below `0.9^7 ≈ 48%` even after weeks offline, preventing extreme re-entry penalties.

---

### 4.9 — Remove Stablecoins from RWA Basket

| Where | Change |
|---|---|
| `config.py:NARRATIVE_BASKETS["RWA"]` | Replace `["USDC", "FDUSD", ...]` with actual RWA tokens, e.g. `["LINK", "AAVE", "PENDLE", "COMP", "CAKE"]` |

---

### 4.10 — Single Import for Risk Constants in portfolio.py

| Where | Change |
|---|---|
| `portfolio.py` | Delete local `STOP_LOSS_PCT` / `TAKE_PROFIT_PCT` constants; add `from src.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT` |

---

## Summary Table

| # | Category | Issue | Severity | Fix Effort |
|---|---|---|---|---|
| 1.1 | Complexity | O(n×m) token→narrative lookup in sell loop | Low (n=2) | Trivial — reverse map |
| 1.2 | Complexity | Double-pass weight normalization | Low (n=10) | Trivial — single pass |
| 1.3 | Complexity | `compute_exhaustion_score` called 2× per narrative | Low | Trivial — cache result |
| 2.1 | Redundancy | Duplicate CMC bulk-quote calls per cycle | **High** | Medium — refactor signal eval API |
| 2.2 | Redundancy | Exhaustion score double-evaluation | Low | Trivial |
| 2.3 | Redundancy | `detect_market_regime` always hardcoded → always TRANSITION | **High** | Medium — wire real data |
| 2.4 | Redundancy | `STOP_LOSS_PCT` / `TAKE_PROFIT_PCT` duplicated in portfolio.py | Medium | Trivial |
| 3.1 | Logic | ALL signal data is fabricated — scores are noise | **Critical** | Medium — populate from CMC quotes |
| 3.2 | Logic | `volume_change_7d_pct` computed from price, not volume (bug) | **High** | Trivial |
| 3.3 | Logic | DEX trending never fetched — "fade hype" signal missing | **Critical** | Medium — wire `get_dex_trending` |
| 3.4 | Logic | Fear & Greed index never fetched | High | Trivial — call `get_fear_greed()` |
| 3.5 | Logic | Token overlap across narratives inflates exposure | Medium | Medium — de-duplicate baskets |
| 3.6 | Logic | RWA basket contains USDC/FDUSD stablecoins | Medium | Trivial |
| 3.7 | Logic | Conviction history unbounded staleness penalty | Low | Trivial — add cap |
| 3.8 | Logic | `pre_trade_check` slippage/position-count guards bypassed | **High** | Trivial — fix call signature |

**Priority order:** Fix 3.1 + 2.1 (unblocks real signal) → Fix 3.2 (corrects metric) → Fix 3.3 + 3.4 (enables real regime/trending) → Fix 3.8 (re-enables risk guards) → Fix 2.3 → remaining items.