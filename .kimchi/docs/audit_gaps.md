# CascadeFade — Gap Analysis Audit

**Auditor:** review sub-agent
**Date:** 2026-06-20
**Phase:** Pre-launch gap analysis
**Severity scale:** BLOCKER > HIGH > MEDIUM > LOW

---

## Verdict: NEEDS_FIXES

The implementation has 6 blockers, 9 high-priority issues, 7 medium issues, and several low-level ones. The agent cannot go live safely without resolving the blockers. The allowlist (50/149 tokens), the TWAK swap command syntax, the missing position-tracking after buys, the broken slippage estimator, missing CMC ID mapping, and the cash-flow bug are the most urgent.

---

## BLOCKERS (cannot go live without)

### B-1: Allowlist has only 50 tokens, not 149
**File:** `src/config.py`
**Lines:** 58–121
**Problem:** `ALLOWLIST` is hardcoded with ~50 tokens. The PLAN and ARCHITECTURE explicitly require all 149 competition-eligible BEP-20 tokens. Any trade outside the 149-token list does not count toward the competition. The variable even has a `TODO` comment: `"Replace with official 149-token list before trading window."` This was never done.
**Impact:** Every token the agent tries to buy that is not in the 50-token subset is rejected silently. The agent is effectively running a tiny fraction of the intended strategy.
**Fix:** Obtain the official 149-token list from the competition contract or organizer and hardcode all of them with correct BSC contract addresses. Several tokens currently in the list (PYTH, JUP, RAYDIUM, BONK, PENGU, WIF, FLOKI, PEPE, MEME, MAGA, AI, AGI) have placeholder/fabricated addresses.

---

### B-2: TWAK `swap` command syntax is unverified — likely wrong
**File:** `src/twak.py`
**Lines:** 68–80
**Problem:** The swap command is constructed as:
```python
cmd = self._build_cmd(["swap", str(amount), from_token, to_token], slippage=slippage, quote_only=quote_only)
```
This produces: `twak swap 5 USDT BNB --chain bsc --json --slippage 0.5`. The TWAK CLI reference docs state the command is `twak swap <amount> <from> <to>`. However, the docs also note that TWAK routes through a aggregator and `from_token`/`to_token` must be contract addresses or registered symbols that TWAK recognizes on BSC. There is no confirmation in the codebase that TWAK accepts bare symbols like "USDT" or "BNB" as valid arguments on BSC — TWAK may require addresses for non-obvious tokens. Additionally, `--chain bsc` may not be the correct flag (could be `--network bsc` or `--chain-id 56`).
**Fix:** Manually test `twak swap 5 USDT BNB --chain bsc --json --slippage 0.5` in a live terminal with a funded wallet BEFORE relying on it. Have a fallback path using contract-address arguments. Document the exact verified command syntax in `POLICY.md`.

---

### B-3: Buy trades never open positions in portfolio tracking
**File:** `src/decision.py`
**Lines:** 193–212 (the buy section in `run_cycle`)
**Problem:** When `_execute_swap("BNB", symbol, size, slippage, quotes, reason)` is called for a buy signal, the position is NOT recorded via `portfolio.add_position()`. Only `log_trade()` is called. When a sell signal fires later, `portfolio.close_position()` is called — but if the position was never added, `close_position` finds no open position and returns an error. Meanwhile, `portfolio.compute_value()` iterates over open positions but this buy position is invisible to it, so position value is never included in portfolio total.
**Impact:** Every buy trade is logged but never tracked. `compute_value()` will show 0 positions_value. The 5% stop-loss and 10% take-profit can never fire because the entry_price is never stored. The 25% drawdown calculation will be wrong (only cash counted, no position value).
**Fix:** After every successful `_execute_swap` for a buy, call:
```python
price = price_map.get(to_sym, {}).get("price", 0.0)
await self.portfolio.add_position(symbol, entry_price=price, amount=amount_out, tx_hash=tx_hash)
```
Also update cash balance in portfolio after every trade (see B-5).

---

### B-4: Portfolio cash is never updated after trades
**File:** `src/decision.py` and `src/portfolio.py`
**Lines:** `decision.py:62` — `value = await self.portfolio.compute_value(quotes, initial_cash)` and all subsequent calls pass the same `initial_cash` unchanged. `portfolio.py:111` — `compute_value()` takes `cash_usd` as a parameter but never persists it. After a swap executes (e.g., $100 BNB → CAKE), the local cash tracking still shows the pre-swap cash balance. On the next cycle, `compute_value` is called with the stale cash value, making all portfolio value calculations incorrect.
**Impact:** Position sizing (`risk.position_size`) will use wrong cash figures. Drawdown calculations will be wrong. The risk manager's pre-trade checks will make incorrect decisions.
**Fix:** After every swap, update the tracked cash balance:
```python
# After buy: cash -= size (in BNB equivalent)
# After sell: cash += exit_value (in BNB equivalent)
await self.portfolio.update_cash(new_cash_amount)
```

---

### B-5: Slippage estimator uses wrong "ideal output" baseline
**File:** `src/quoter.py`
**Lines:** 112–117
**Problem:**
```python
ideal_out = amount_in  # rough equal-value assumption
if ideal_out > 0:
    slippage = max(0, (ideal_out - amount_out) / ideal_out)
```
`amount_in` is in units of `from_symbol` (e.g., 5 BNB = ~$1500). `amount_out` is in units of `to_symbol` (e.g., ~1500 USDT). If BNB = $300 and USDT = $1.00, then 5 BNB = 1500 USDT. The calculation gives `slippage ≈ 0`. This happens to be numerically correct for BNB→USDT, but purely by accident. For CAKE→BNB where CAKE = $2.50 and BNB = $300, `amount_in=100 CAKE = $250`, `amount_out` might be 0.8 BNB = $240, and the formula gives `(250 - 240) / 250 = 4%` — which is correct, but only because CAKE and BNB are both near their dollar value. The "equal value assumption" happens to be valid when both tokens are near-USD-pegged or when the assumption accidentally cancels out. For non-stable pairs with very different USD prices, this is wrong.
**Impact:** Slippage estimates for some pairs will be inflated; for others, deflated. The 1% slippage gate may allow bad trades or skip good ones.
**Fix:** Compute ideal output using USD prices:
```python
from_price_usd = price_map.get(from_symbol, {}).get("price", None) or 1.0  # needs price context
ideal_out_usd = amount_in * from_price_usd
to_price_usd = price_map.get(to_symbol, {}).get("price", None) or 1.0
ideal_out = ideal_out_usd / to_price_usd  # expected output in to_token units
slippage = max(0, (ideal_out - amount_out) / ideal_out) if ideal_out > 0 else 0.0
```
Note: `quoter.py` has no access to `price_map`. The fix requires either passing prices into the quoter or computing slippage in `decision.py` where prices are available.

---

### B-6: CMC bulk quotes use symbol lookup without ID mapping
**File:** `src/cmc_client.py` and `src/decision.py`
**Lines:** `cmc_client.py:62` — `if cid and cid.isdigit(): ids.append(cid) ... else: symbols.append(sym)`; `decision.py:167` — `symbol_map = {k: "" for k in ALLOWLIST}`
**Problem:** CMC's `/v2/cryptocurrency/quotes/latest` endpoint accepts `symbol=A,B,C` for up to a certain number of symbols. However, when using symbol-only lookup, the API returns ambiguous results for symbols that overlap with other chains or older API versions. More critically, CMC requires a Pro API key for `/v2/` endpoints — the `X-CMC_PRO_API_KEY` header is used, but the free/Basic tier may not support bulk symbol queries to 50 tokens simultaneously. The current code passes `""` as the CMC ID for every token, relying entirely on symbol-based lookup. If CMC's symbol dedup is case-insensitive and there are conflicts, results are unpredictable.
**Impact:** Data fetch may return stale, partial, or zero data for some tokens. The entire signal quality degrades.
**Fix:** Map symbols to CMC numeric IDs and use `id=` parameter instead of `symbol=` for reliability. Populate `CMC_SYMBOL_TO_ID` in `config.py` at startup (or hardcode known IDs for the 149 tokens). Verify the free tier rate limits: 50 calls/day (30-min intervals) × 1 call/cycle = well within limits only if the bulk endpoint works.

---

## HIGH PRIORITY (degrades performance or safety)

### H-1: Cache is never read before fetching — cache is effectively dead code
**File:** `src/decision.py`
**Lines:** 147–154 (`_fetch_quotes`, `_fetch_trending`, `_fetch_fear_greed`)
**Problem:** `_fetch_quotes()` always calls `cmc.get_bulk_quotes()` directly, never checking `cache.get_quote()` first. `_fetch_trending()` and `_fetch_fear_greed()` do check cache, but `_fetch_quotes()` does not. This means on every cycle (every 30 minutes), the agent makes a live CMC API call for all 149 tokens even if the data is already cached and fresh. This wastes rate-limit credits and increases latency.
**Impact:** With 50 tokens and 48 cycles/day, this could burn through the free 15K credits/month quickly. At 48 cycles × 50 tokens per bulk call (still counts as 1 call), that's 48 calls/day = ~1,440/month, which is fine. But if the bulk endpoint silently falls back to per-token calls (CMC may do this internally), that's 48 × 50 = 2,400 calls/day = 72,000/month, which exceeds the free tier. The cache was designed to prevent this but is not being used.
**Fix:** In `_fetch_quotes()`, check cache first for all tokens. Only call `get_bulk_quotes()` for tokens with stale or missing cache entries.

---

### H-2: `Cache` is a class with class-level `_db` shared across all instances
**File:** `src/cache.py`
**Lines:** 18–19
**Problem:**
```python
class Cache:
    _db: aiosqlite.Connection | None = None  # class variable — shared!
```
Every `Cache()` instantiation shares the same `_db` connection. If multiple instances are created (e.g., in tests, or in `agent.py` which creates one `Cache()` instance per `Agent`), they all share one connection. When that connection is closed by one instance (`await cache.close()`), all other instances break.
**Impact:** Silent corruption or `RuntimeError: Cannot operate on a closed database`. This is a latent bug that may surface during long-running operation.
**Fix:** Make `_db` an instance variable (move into `__init__`). Add proper async context manager (`__aenter__`/`__aexit__`) or ensure a single shared cache instance is used everywhere.

---

### H-3: SQLite WAL checkpoint — concurrent writers from 3 separate connections
**Files:** `src/cache.py`, `src/log.py`, `src/portfolio.py`
**Problem:** Three different classes (`Cache`, `TradeLogger`, `Portfolio`) each open their own independent `aiosqlite.connect()` connection to the same `cascade_fade.db` file. All three set `PRAGMA journal_mode=WAL`. WAL mode allows concurrent readers but a single writer blocks all other writers. When `TradeLogger.log_trade()` runs a `BEGIN IMMEDIATE` transaction (which acquires a write lock), any concurrent write from `Cache` or `Portfolio` will be blocked or fail.
**Impact:** Under load, especially if the agent runs for many cycles, concurrent database writes from logging + cache updates + portfolio snapshots can deadlock or produce `database is locked` errors.
**Fix:** Use a single shared SQLite connection for all database operations, or use a connection pool with a write lock. Alternatively, consolidate all tables into one connection class (`Database`) that manages a single WAL connection and provides methods for all table operations.

---

### H-4: `decisions.py` — cash value goes stale after sells but never after buys
**File:** `src/decision.py`
**Lines:** 109 (after sell loop), 122 (after heartbeat), 133 (after buy loop)
**Problem:** `cash` is captured from `value["cash"]` after the sell loop (line 109) but then reused for all subsequent `compute_value()` calls without being updated after heartbeat or buy executions. More critically: after `_execute_swap()` for a buy, cash is spent but never deducted from the tracked `cash` variable.
**Related to:** B-4 (same root cause, amplifying effect).
**Fix:** See B-4.

---

### H-5: `test_risk.py` uses pytest-style async functions but has no pytest fixtures
**File:** `tests/test_risk.py`
**Lines:** 20, 36, 48, 65, 95
**Problem:** Tests use `async def test_*(risk: RiskManager)` which pytest treats as test functions requiring a `risk` fixture. No fixtures are defined. The tests only pass when run as a standalone script (`python -m tests.test_risk`) which bypasses pytest entirely and imports `RiskManager` directly. When run with `pytest`, all 5 tests ERROR with "fixture 'risk' not found."
**Impact:** CI will fail if pytest is the test runner. The test file appears to have tests but they are invisible to pytest.
**Fix:** Either (a) add a pytest fixture for `risk` in a `conftest.py`, or (b) rename test functions so pytest doesn't auto-collect them, or (c) add `pytest.mark.asyncio` and define fixtures, or (d) mark the file as a script (`pytestmark = pytest.mark.skip`).

---

### H-6: `CMC_DEX_TRENDING` configured as GET but may require POST
**File:** `src/config.py` line 16
**Problem:** `CMC_DEX_TRENDING = "/v1/dex/tokens/trending/list"` is defined but the code uses `self._request("GET", CMC_DEX_TRENDING)`. According to CMC API documentation, some trending/list endpoints require POST with a JSON body. The `cmc_client.py` `_request()` method only supports query params for GET and form-encoded body for POST — it does not support JSON body for POST requests.
**Impact:** If the endpoint requires POST, `get_dex_trending()` always fails silently and returns an empty list. The sell condition "token enters top-3 DEX trending" never fires based on real data.
**Fix:** Verify the actual HTTP method for CMC DEX trending endpoint. If POST is required, add JSON body support to `_request()`:
```python
async def _request(self, method: str, path: str, params=None, json_body=None, **kwargs):
    ...
    if json_body:
        kwargs["json"] = json_body
```

---

### H-7: `eth_utils` not in `requirements.txt` but used in `utils.py`
**File:** `requirements.txt` vs `src/utils.py` line 43
**Problem:** `to_checksum()` in `utils.py` imports `from eth_utils import to_checksum_address`. `eth_utils` is not listed in `requirements.txt`. When `utils.py` is imported, it will fail with `ModuleNotFoundError: No module named 'eth_utils'`.
**Impact:** Any import of `src.utils` (which happens in `agent.py` via `setup_logging`) will crash on startup.
**Fix:** Add `eth-utils>=0.5.0` to `requirements.txt`. Alternatively, remove the `to_checksum` function if it is not used anywhere critical (check all callers).

---

### H-8: QuoterV2 `DECIMALS` map is incomplete for the 50-token allowlist
**File:** `src/quoter.py`
**Lines:** 51–79
**Problem:** The `DECIMALS` dictionary covers about 30 tokens but is missing: PYTH, JUP, RAY, RAYDIUM, BONK, PENGU, WIF, FLOKI, PEPE, MEME, MAGA, AI, AGIX. For unknown tokens, the code defaults to 18 decimals. PYTH has 6 decimals (not 18), and several Solana-migrated tokens have non-18 decimals on BSC. Using wrong decimals produces incorrect `amount_in_wei` and `amount_out` calculations.
**Impact:** QuoterV2 slippage estimates for PYTH and other non-18-decimal tokens will be wildly wrong (off by factors of 10^12), causing wrong accept/reject decisions.
**Fix:** Add accurate decimal values for all tokens in the allowlist. PYTH on BSC is 6 decimals (verified). Research each unknown token.

---

### H-9: No position opening after heartbeat buy
**File:** `src/decision.py`
**Lines:** 115–122 (heartbeat section)
**Problem:** When a heartbeat swap executes (e.g., USDT → BNB), if the pair result is BNB, the agent now holds BNB. This is tracked as a position in the `portfolio` table only if `add_position` is called. The heartbeat buy is for a $5 USDT → BNB swap. BNB is in the allowlist. But `add_position` is never called after the heartbeat swap. The portfolio will think it holds no BNB, compute wrong position values, and the heartbeat will trigger again in 22 hours.
**Impact:** Heartbeat will fire every cycle because the agent never considers itself as holding BNB. This will generate hundreds of tiny BNB/USDT swaps that waste gas and may violate the spirit of the "one meaningful trade per day" requirement.
**Fix:** After a heartbeat swap, call `add_position` for the received token (BNB in this case).

---

## MEDIUM (affects scoring or experience)

### M-1: No live test swap confirmed on BSCScan
**Files:** `scripts/test_swap.py` exists but has never been run successfully (no tx hash saved in `logs/test_swap.txt`). The PLAN requires a live mainnet swap confirmed on BSCScan before going live.
**Impact:** Cannot verify that the TWAK execution path works before the trading window opens.
**Fix:** Run `python scripts/test_swap.py` with a funded wallet and save the confirmed tx hash.

---

### M-2: No 2+ hour paper run completed
**File:** `src/agent.py`
**Problem:** The agent has never been run in paper mode for 2 hours. The PLAN requires at least a 2-hour paper run to verify no crashes or rate-limit errors. With the current bugs (stale cash, dead cache, missing position tracking), a long run will produce increasingly incorrect decisions.
**Fix:** Fix bugs first, then run paper mode for 4+ hours.

---

### M-3: `AGENTS.md` exists but is not populated
**File:** `AGENTS.md`
**Problem:** The file exists but appears to be a default/template file, not specific to CascadeFade.
**Impact:** If this file is intended for multi-agent coordination, it should be relevant.
**Fix:** Either populate it correctly or remove it.

---

### M-4: Docs say "updating to 149 tokens" but this was never done
**Files:** `SUBMISSION.md`, `README.md`, `ARCHITECTURE.md`
**Problem:** `SUBMISSION.md` line 10 says "149-token allowlist enforced (top 50 built; updating to 149)" with a checkbox. This is listed as a pending item. The ARCHITECTURE.md says "hardcoded 149-token competition allowlist" but it is not actually 149 tokens.
**Impact:** Judges reading the docs see a claim that does not match the code.
**Fix:** Either update the allowlist to 149 tokens (B-1) or update all docs to accurately reflect the current state (50 tokens).

---

### M-5: No `CMC_SYMBOL_TO_ID` mapping populated
**File:** `src/config.py`
**Lines:** 123
**Problem:** `CMC_SYMBOL_TO_ID: dict[str, int] = {}` is defined but never populated. The comment says "populated at runtime if not cached" but there's no code that does this. `cmc_client.py` uses empty string IDs which fall back to symbol lookup.
**Fix:** Either populate the map with known CMC IDs for the 149 tokens (static data), or implement a runtime lookup function that resolves symbol → CMC ID via a one-time API call.

---

### M-6: `signal.py` — confidence score is based on `abs(change_7d) / 20.0`
**File:** `src/signal.py`
**Lines:** 90
**Problem:** Confidence is `min(abs(change_7d) / 20.0, 1.0)`. This rewards high 7d changes, but the signal is supposed to reward *low-attention* tokens with *modest* positive drift. A 7d change of 50% (extreme hype) would score confidence 1.0, which is the opposite of the intended signal. A 2% gain over 7 days scores 0.1 confidence, which is more appropriate for "low attention."
**Impact:** The candidate ranking will preferentially pick already-hyped tokens with large gains, undermining the core alpha thesis.
**Fix:** Invert or cap the confidence metric. Consider: `confidence = min(max(0, 1 - abs(change_7d) / 30.0), 1.0)` to reward moderate (5–15%) movers over extreme (>30%) movers. Or use volume rank as a confidence input (lower volume rank = higher confidence).

---

### M-7: `decision.py` — `portfolio_value=0.0` hardcoded in log_trade
**File:** `src/decision.py`
**Lines:** 201
**Problem:** `await self.logger.log_trade(..., portfolio_value=0.0, ...)` passes `0.0` for portfolio_value. The comment says "updated later by portfolio.compute_value" but `compute_value` only writes to `portfolio_snapshots`, not back to the trades table. The `realized_pnl` is also passed as `None`.
**Impact:** The trade log has incomplete data for audit purposes. PnL cannot be reconstructed from the log alone.
**Fix:** After `compute_value()`, update the trade record with actual portfolio_value and realized_pnl.

---

## LOW (cosmetic or non-critical)

### L-1: Logging level is not propagated to components
**File:** `src/agent.py`
**Lines:** 44
**Problem:** `setup_logging()` is called with `LOG_LEVEL` from env, but child modules (`cascadefade.cmc`, `cascadefade.twak`, etc.) call `logging.getLogger("cascadefade.*")` and inherit the level. However, `utils.py` uses `logging.getLogger("cascadefade")` (no suffix) which may not propagate to children. The format string in `setup_logging` may not apply to all loggers.
**Impact:** Inconsistent log formatting across modules.
**Fix:** Call `logging.getLogger()` with the full name in all modules, or configure the root logger explicitly.

---

### L-2: `risk.py` — `select_heartbeat_pair` uses hardcoded BNB/USDT
**File:** `src/risk.py`
**Lines:** 105–114
**Problem:** The heartbeat pair is always BNB/USDT. If BNB is not in the allowlist or the wallet has no USDT, the heartbeat fails. The PLAN says the heartbeat should use "a tiny qualifying swap (e.g., $5 USDT → BNB) within the 149-token list."
**Impact:** Minor. Works as long as the wallet has both BNB and USDT.
**Fix:** Make the pair configurable via env var. Fall back to a pair that exists in the wallet.

---

### L-3: No `.env` file — only `.env.example`
**File:** (no `.env`)
**Problem:** The agent requires `CMC_API_KEY`, `TWAK_WALLET_PASSWORD`, etc. The `.gitignore` presumably excludes `.env`, so the actual secrets must be created manually. The `.env.example` exists but the onboarding instructions assume the user creates `.env` from it.
**Impact:** First-time setup friction. Not a blocker.
**Fix:** Document the `.env` creation step clearly in README.

---

### L-4: `POLICY.md` is a stub
**File:** `POLICY.md`
**Problem:** The file exists and has headings but may not have actual policy content.
**Fix:** Ensure `POLICY.md` documents the developer-defined limits (daily spend cap, allowlist, max slippage, kill switch) as required by the PLAN.

---

### L-5: `src/__init__.py` is empty
**File:** `src/__init__.py`
**Problem:** The package init file is empty (no exports, no version, no doc). This is fine but could include `__version__` for debugging.
**Fix:** Add `__version__ = "0.1.0"` and optionally export key classes.

---

## SUMMARY TABLE

| ID | Severity | File | Issue |
|----|----------|------|-------|
| B-1 | BLOCKER | `src/config.py` | Allowlist has 50/149 tokens; many addresses are fabricated |
| B-2 | BLOCKER | `src/twak.py` | TWAK swap command syntax unverified; may not accept symbol names |
| B-3 | BLOCKER | `src/decision.py` | Buy trades never call `portfolio.add_position()` — positions invisible |
| B-4 | BLOCKER | `src/decision.py`, `src/portfolio.py` | Portfolio cash never updated after trades — all valuations wrong |
| B-5 | BLOCKER | `src/quoter.py` | Slippage formula uses `amount_in` as baseline instead of USD-equivalent |
| B-6 | BLOCKER | `src/cmc_client.py` | No CMC ID mapping; bulk quotes may return ambiguous/stale data |
| H-1 | HIGH | `src/decision.py` | Cache is never read before fetching — defeats the cache entirely |
| H-2 | HIGH | `src/cache.py` | `Cache._db` is class-level shared — connection lifecycle bugs |
| H-3 | HIGH | `src/cache.py`, `src/log.py`, `src/portfolio.py` | 3 separate WAL connections to same DB — writer contention/locks |
| H-4 | HIGH | `src/decision.py` | Cash value stale after sells; amplifies B-4 |
| H-5 | HIGH | `tests/test_risk.py` | Pytest fixtures missing — tests pass only as scripts, fail under pytest |
| H-6 | HIGH | `src/config.py`, `src/cmc_client.py` | DEX trending endpoint may require POST not GET |
| H-7 | HIGH | `requirements.txt` | `eth_utils` missing from dependencies |
| H-8 | HIGH | `src/quoter.py` | DECIMALS map incomplete; PYTH uses wrong decimals (6 not 18) |
| H-9 | HIGH | `src/decision.py` | Heartbeat buy never calls `add_position` — BNB not tracked |
| M-1 | MEDIUM | `scripts/test_swap.py` | No live swap confirmed on BSCScan |
| M-2 | MEDIUM | (none) | No 2+ hour paper run completed |
| M-3 | MEDIUM | `AGENTS.md` | File exists but is not populated |
| M-4 | MEDIUM | `SUBMISSION.md`, `README.md`, `ARCHITECTURE.md` | Docs overstate allowlist size |
| M-5 | MEDIUM | `src/config.py` | `CMC_SYMBOL_TO_ID` always empty |
| M-6 | MEDIUM | `src/signal.py` | Confidence metric inverts the alpha thesis |
| M-7 | MEDIUM | `src/decision.py` | Trade log written with `portfolio_value=0.0` and `realized_pnl=None` |
| L-1 | LOW | `src/agent.py`, `src/utils.py` | Logger naming inconsistency |
| L-2 | LOW | `src/risk.py` | Heartbeat pair hardcoded to BNB/USDT |
| L-3 | LOW | (no `.env`) | Setup friction for first-time users |
| L-4 | LOW | `POLICY.md` | May be a stub |
| L-5 | LOW | `src/__init__.py` | Empty init file |