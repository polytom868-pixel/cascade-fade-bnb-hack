# Security Audit Report — CascadeFade

**Date:** 2026-06-20
**Reviewer:** Kimchi Agent (Review Sub-Agent)
**Files Audited:** agent.py, cache.py, cmc_client.py, config.py, decision.py, log.py, portfolio.py, quoter.py, risk.py, signal.py, twak.py, utils.py

---

## Verdict: NEEDS_FIXES

---

## CRITICAL Issues

### 1. `quoter.py` — Blocking synchronous web3 calls in async event loop

**File:** `src/quoter.py`
**Severity:** CRITICAL
**Category:** Async Safety / Blocking I/O

`estimate_slippage_single()` (line 61) and `get_balance()` (line 96) are regular synchronous methods that call `web3.eth.contract(...).functions.quoteExactInputSingle(...).call()` and `self.w3.eth.get_balance(...)`. These are **blocking** calls that will freeze the asyncio event loop when called from async context.

Every call site in `decision.py` invokes these synchronously from async functions:
```python
# decision.py line 131
q = self.quoter.estimate_slippage_single(from_sym, to_sym, HEARTBEAT_SIZE_USD)
```
```python
# decision.py lines 154-160 (loop over ALL allowlist tokens)
q = self.quoter.estimate_slippage_single("BNB", sym, HEARTBEAT_SIZE_USD, ...)
```

During `run_cycle`, this loop calls `estimate_slippage_single` **~50 times** (once per allowlist token), each blocking for a Web3 RPC round-trip. At ~200ms per call, that is ~10 seconds of **blocking the event loop** — no other async tasks can run during this time. On slow RPC responses, this could be 30+ seconds.

**Fix:** Wrap synchronous calls with `asyncio.get_event_loop().run_in_executor(None, functools.partial(self.quoter.functions.quoteExactInputSingle(...).call))` or use `web3.AsyncWeb3` with async HTTP provider.

---

### 2. `config.py` — Fake/placeholder token contract addresses

**File:** `src/config.py` lines 54–62
**Severity:** CRITICAL
**Category:** Financial Safety / Wrong Token Addresses

The ALLOWLIST contains fabricated addresses for 20+ meme and newer tokens:

```python
"PYTH": "0xD3c0A2C8F3d0e9aF3C5D6B4F8A9E3c2D1B0A4F7e",
"JUP": "0x0231f9e4E44c4F338F9D24bE2A6C3f5E8A9D7C6B",
"RAY": "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4",  # duplicates PCS_V3_SMART_ROUTER!
"RAYDIUM": "0x14f5AB83D0bd40E75C8222255bc855a974568Dd5",
"BONK": "0x15f6AC83D0bd40E75C8222255bc855a974568Dd6",
...
```

**RAY address is the PancakeSwap V3 Smart Router address** — not a RAY token. The fake-addresses-with-sequential-suffixes pattern is trivially identifiable as fabricated.

If the agent buys RAY using `twak swap 1 BNB RAY`, TWAK resolves the symbol internally. If TWAK falls back to the hardcoded ALLOWLIST address, it will attempt to swap against the PCS router contract, potentially burning BNB or sending funds to an unintended address. Meme coin swaps using PYTH, JUP, WIF, PEPE etc. are all at risk.

**Fix:** Remove non-major tokens from ALLOWLIST, or obtain and verify real BEP-20 contract addresses from an authoritative source (CoinGecko API, CMC contract mapping, or on-chain verification). Add address checksum validation.

---

### 3. `decision.py` — `amount_out` division by zero silently produces zero or inf

**File:** `src/decision.py` line 200
**Severity:** CRITICAL
**Category:** Financial Safety / Data Integrity

```python
amount_out = amount * (p_in / p_out) if p_out else 0,
```

If `p_out` (destination token price) is extremely small but non-zero (e.g., a low-price meme coin), `amount_out` will be enormous. If `p_out` is exactly zero (token not in price map), `amount_out` defaults to 0 — but if `p_in` is zero, the result is `NaN`. Python float NaN propagates into the database as NULL or NaN string, corrupting the trade log.

More critically: if both prices are present but `p_out` is 0.00001 (1 cent token) and `p_in` is 300 (BNB), the logged `amount_out` will be `amount * 30,000,000` — a completely unrealistic token amount that will appear in the trade log as if the swap succeeded at that quantity.

**Fix:** Validate that `p_in` and `p_out` are both positive and within reasonable bounds before computing `amount_out`. Add bounds checking: reject if `amount_out > amount * 1e6` or similar sanity cap.

---

## HIGH Issues

### 4. `log.py` — Uncommitted transaction on exception during `log_trade`

**File:** `src/log.py` lines 40–70
**Severity:** HIGH
**Category:** Error Handling / Data Integrity

```python
await db.execute("BEGIN IMMEDIATE")
cursor = await db.execute("INSERT INTO trades(...) VALUES(...)", (...))
row_id = cursor.lastrowid
await db.commit()
```

If the INSERT fails (e.g., constraint violation, disk full), there is no `except` block with `ROLLBACK`. The `BEGIN IMMEDIATE` transaction is left open and the function returns without raising — the caller has no indication the trade was not logged. In live mode, the trade executes but is never recorded, creating an irreconcilable state between TWAK and the local journal.

**Fix:** Wrap in try/except:
```python
try:
    await db.execute("BEGIN IMMEDIATE")
    cursor = await db.execute("INSERT INTO trades(...)")
    row_id = cursor.lastrowid
    await db.commit()
except Exception:
    await db.rollback()
    raise
```

### 5. `agent.py` — Shutdown race: cycle executes after shutdown signal

**File:** `src/agent.py` lines 110–124
**Severity:** HIGH
**Category:** Race Condition

```python
while not _shutdown_requested.is_set():
    try:
        await asyncio.wait_for(_shutdown_requested.wait(), timeout=self.interval.total_seconds())
    except asyncio.TimeoutError:
        pass

    if _shutdown_requested.is_set():  # ← race window here
        break

    await self.run_cycle()  # ← could still execute after SIGINT received
    await self.health_check()
```

Between the `if _shutdown_requested.is_set()` check and `await self.run_cycle()`, a SIGINT could arrive. The cycle will still execute because the check already passed. A second SIGINT would trigger `_signal_handler` to raise `KeyboardInterrupt` (Python's default for SIGINT), but only if the previous handler didn't already set the flag.

**Fix:** Use a lock or check the event inside the cycle's exception handler:
```python
while not _shutdown_requested.is_set():
    await asyncio.wait_for(asyncio.sleep(self.interval), timeout=self.interval.total_seconds())
    if _shutdown_requested.is_set():
        break
    await self.run_cycle()
```

### 6. `twak.py` — Password in command-line arguments visible to all users

**File:** `src/twak.py` lines 37–39, 59
**Severity:** HIGH
**Category:** Secrets Management

```python
if self.password:
    cmd += ["--password", self.password]
```

The TWAK password (wallet unlock credentials) is passed as a command-line argument. This is logged:
```python
cmd_str = " ".join(shlex.quote(c) for c in cmd)
logger.info("TWAK cmd: %s", cmd_str)  # logs full command including --password
```

Passwords in command-line arguments are visible via `ps aux`, `/proc/<pid>/cmdline`, and system logs. Additionally, if `TWAK_WALLET_PASSWORD` is set in a shell profile or `.env`, it appears in shell history.

**Fix:** TWAK supports password via environment variable (e.g., `TWAK_WALLET_PASSWORD` passed to subprocess env, not as an arg). Check TWAK documentation for stdin/password-pipe option. If not available, document the risk prominently and recommend against live trading with this configuration.

### 7. `cmc_client.py` — `RuntimeError` in `_do()` masks JSON parse failures as retriable

**File:** `src/cmc_client.py` lines 42–52
**Severity:** HIGH
**Category:** Error Handling

```python
async with session.request(method, url, **kwargs) as resp:
    data = await resp.json()  # ← raises aiohttp.ClientError if body is not JSON
    if resp.status == 429:
        raise asyncio.TimeoutError(...)
    if resp.status != 200:
        raise RuntimeError(f"CMC {resp.status}: ...")
```

`aiohttp.ClientError` is listed in the retry exceptions tuple — good. However, the code raises `RuntimeError` for non-200 responses, and `RuntimeError` is also in the retry tuple. A 500 from CMC (internal error) will retry 3 times with backoff before finally raising the `RuntimeError`. While this is not wrong, it means a 500 error takes ~13.5 seconds (1.5 + 3 + 4.5 backoff) to surface to the caller. More critically, if the response body is not valid JSON (e.g., a 502 proxy error page), `resp.json()` raises `aiohttp.ClientError` which is correctly retried, but the error message from the 4th attempt will be the last `ClientError`, not the actual HTTP status.

**Fix:** Add `resp.status` checking before `resp.json()`, and catch JSON decode errors separately. Return a more descriptive error that includes the HTTP status for 5xx responses.

---

## MEDIUM Issues

### 8. `portfolio.py` / `decision.py` — In-memory cash not persisted between cycles

**File:** `src/portfolio.py` lines 140–145; `src/decision.py` lines 78–79
**Severity:** MEDIUM
**Category:** Financial Safety / Data Integrity

Cash is passed in-memory from `compute_value` back to the caller and used in the next cycle:
```python
# decision.py run_cycle
value = await self.portfolio.compute_value(quotes, cash)
cash = value["cash"]   # ← updated in-memory only
```

`portfolio.initialize_cash()` only inserts the initial snapshot — it has no "update cash" method. If the process crashes after a buy trade (cash decremented in memory) but before the next `compute_value` call, the next startup will re-initialize cash to `initial_cash` (1000.0), double-counting the position. However, `compute_value` reads cash from caller, not DB, so the crash-recovery state depends on whether the position was recorded.

Specifically: if the agent crashes after `_execute_swap` calls `log_trade` but before the next cycle's `compute_value`, the position IS recorded (via `add_position` → `log_trade`), but the cash reduction is not. This means the portfolio will show the position + full original cash, overstating total value.

**Fix:** Add `update_cash()` to portfolio that persists the cash balance to `portfolio_snapshots`. Call it at the end of each cycle.

### 9. `config.py` — No checksum validation on ALLOWLIST addresses

**File:** `src/config.py`; used in `decision.py` lines 156–159
**Severity:** MEDIUM
**Category:** Input Validation / Web3 Safety

`utils.to_checksum()` exists but is never called. The ALLOWLIST contains mixed-case addresses (e.g., `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4`). Passing non-checksum addresses to Web3 contract calls may silently fail or route to wrong addresses on some chains.

**Fix:** Validate and checksum all ALLOWLIST addresses at startup:
```python
for sym, addr in ALLOWLIST.items():
    if addr:
        ALLOWLIST[sym] = to_checksum(addr)
```

### 10. `decision.py` — No validation that token addresses are non-zero before swapping

**File:** `src/decision.py` lines 156–159
**Severity:** MEDIUM
**Category:** Input Validation / Financial Safety

```python
from_addr = ALLOWLIST.get("BNB")
to_addr = ALLOWLIST.get(cand.symbol)
q = self.quoter.estimate_slippage_single("BNB", cand.symbol, size, from_addr, to_addr)
```

If `cand.symbol` is not in ALLOWLIST, `to_addr` is `None`. `estimate_slippage_single` returns `{"error": "Missing token addresses", "slippage_pct": 1.0}`. The code then checks `MAX_SLIPPAGE_PCT` (1%) against `slippage_pct=1.0` (100%) — so it would correctly deny the trade. However, if `slippage_pct` were, say, 0.5 instead of 1.0, the check could pass with a missing address.

**Fix:** Require both addresses to be non-None before calling quoter:
```python
if not from_addr or not to_addr:
    summary["actions"].append(f"buy_{cand.symbol}_denied: missing_address")
    continue
```

### 11. `cmc_client.py` — `get_fear_greed` silently returns None on all errors

**File:** `src/cmc_client.py` lines 107–115
**Severity:** MEDIUM
**Category:** Error Handling

```python
try:
    data = await self._request("GET", CMC_FEAR_GREED)
    d = data.get("data", [{}])[0]
    return {"value": d.get("value", 50), "classification": d.get("value_classification", "Neutral")}
except Exception as exc:
    logger.warning("Fear & Greed fetch failed: %s", exc)
    return None
```

Catches all exceptions silently. If the CMC fear & greed endpoint changes its response format (e.g., `data` is a dict instead of a list), this returns `None` without any indication that the data was malformed vs. simply unavailable. The caller in `decision.py` handles `None` but treats it the same as a cache miss.

**Fix:** Return a structured error or raise a specific exception. Distinguish between "endpoint unavailable" and "malformed response."

### 12. `risk.py` — `check_heartbeat` relies on last trade timestamp only

**File:** `src/risk.py` lines 40–60
**Severity:** MEDIUM
**Category:** Financial Safety / Heartbeat Logic

```python
if last_ts:
    last = datetime.fromisoformat(last_ts)
    hours_since = (now - last).total_seconds() / 3600
    if hours_since < 22:
        return {"needed": False, ...}
```

If the last "trade" was a `decision` (no-signal log entry with `side="decision"`), `get_last_trade_ts()` still returns that timestamp, so the heartbeat might not fire even though no actual swap was executed. In paper mode, even real "swaps" are logged with `tx_hash="PAPER"`.

**Fix:** Filter `get_last_trade_ts()` to only count `status IN ('confirmed', 'paper')` entries, or add a separate `get_last_swap_ts()` method.

### 13. `cache.py` — No input validation on `symbol` parameter

**File:** `src/cache.py` lines 71, 78
**Severity:** MEDIUM
**Category:** Input Validation / SQL Injection

```python
async with db.execute(
    "SELECT data FROM cmc_quotes WHERE symbol=? AND ts>?", (symbol, cutoff)
) as cur:
```

The `symbol` is passed as a bound parameter (`?`), so SQL injection is not possible here. However, there is no validation that `symbol` is a non-empty string, no uppercase normalization, and no length limit. A malicious or malformed symbol could cause unexpected behavior.

**Fix:** Add validation: `if not symbol or len(symbol) > 20: return None`.

---

## LOW Issues

### 14. `signal.py` — Magic number 0.25 hardcoded, duplicating `MAX_DRAWDOWN_PCT`

**File:** `src/signal.py` lines 79–81
**Severity:** LOW
**Category:** Code Quality / DRY

```python
if portfolio_drawdown_pct >= 0.25:
    return SignalState(symbol, "sell", f"drawdown kill: {portfolio_drawdown_pct:.2%}")
```

Hardcodes 0.25 instead of using `MAX_DRAWDOWN_PCT` from config. If `MAX_DRAWDOWN_PCT` is changed via env var, the signal engine's kill threshold diverges from the RiskManager threshold.

**Fix:** Import `MAX_DRAWDOWN_PCT` from config and use it in `evaluate_sell`.

### 15. `twak.py` — `cmd_str` logged before `shlex.quote` in production

**File:** `src/twak.py` lines 54–55
**Severity:** LOW
**Category:** Logging Safety

```python
cmd_str = " ".join(shlex.quote(c) for c in cmd)
logger.info("TWAK cmd: %s", cmd_str)
```

`shlex.quote` does not redact the content — it only quotes it for shell safety. If the password is in `cmd`, it will appear in logs as `'--password' 'mypassword'`. The logging at INFO level means it appears in normal production logs.

**Fix:** Redact sensitive fields before logging:
```python
safe_cmd = [c if not any(flag in cmd[i-1] for flag in ['--password']) else '***' for i, c in enumerate(cmd)]
```

### 16. `decision.py` — Missing `await` on `close_position` in `_execute_sell`

**File:** `src/decision.py` line 221
**Severity:** LOW
**Category:** Async Correctness

```python
await self.portfolio.close_position(symbol, price, result.get("tx_hash", ""))
```

This is correctly awaited. However, the `pnl` calculation on line 224 uses `price` from the function parameter, which is the current market price — not the actual exit price from the swap. If the swap executed at a different price (due to slippage), the PnL logged may be inaccurate.

**Fix:** Use the actual swap output price if available in `result`.

### 17. `cache.py` — `Cache` instances share class-level `_db = None` initialization

**File:** `src/cache.py` line 14
**Severity:** LOW
**Category:** Async / Instance Isolation

```python
class Cache:
    _db: aiosqlite.Connection | None = None
```

This is an instance variable declaration (not class variable), so each instance gets its own `_db`. However, the type annotation at class scope is slightly ambiguous. Each of Portfolio, Cache, and TradeLogger creates its own independent `aiosqlite.connect()` to the same DB file. WAL mode handles concurrent access, but there is no coordination — if the DB file is locked (e.g., another process holds a write lock), each will retry independently.

**Fix:** No change needed — behavior is correct. Clarify comment: `# Instance variable, not shared across instances`.

### 18. `utils.py` — `retry_async` factory function pattern is fragile

**File:** `src/utils.py` lines 68–82
**Severity:** LOW
**Category:** Code Quality

The factory pattern works but the calling convention is non-obvious. The caller passes `_do` (a closure referencing `session` and `url`), not an awaitable directly. If `session` goes out of scope, `_do()` will capture a closed session.

**Fix:** Document the closure capture pattern. Consider making `retry_async` accept `(session, method, url, **kwargs)` directly.

---

## Summary Table

| File | Severity | Issue |
|------|----------|-------|
| `quoter.py` | CRITICAL | Blocking web3 calls in async event loop |
| `config.py` | CRITICAL | Fake/placeholder token contract addresses |
| `decision.py` | CRITICAL | `amount_out` division produces inf/NaN on bad prices |
| `log.py` | HIGH | Uncommitted transaction on INSERT failure |
| `agent.py` | HIGH | Shutdown race allowing post-signal cycle execution |
| `twak.py` | HIGH | Password visible in command-line args and logs |
| `cmc_client.py` | HIGH | RuntimeError masking of JSON parse failures |
| `portfolio.py` | MEDIUM | In-memory cash not persisted between cycles |
| `config.py` | MEDIUM | No checksum validation on ALLOWLIST addresses |
| `decision.py` | MEDIUM | No validation that token addresses are non-None |
| `cmc_client.py` | MEDIUM | `get_fear_greed` silently returns None on all errors |
| `risk.py` | MEDIUM | Heartbeat check may not count paper "swaps" |
| `cache.py` | MEDIUM | No input validation on symbol parameter |
| `signal.py` | LOW | Magic number 0.25 duplicates `MAX_DRAWDOWN_PCT` |
| `twak.py` | LOW | Password not redacted in log output |
| `decision.py` | LOW | PnL calculation uses market price, not actual swap price |
| `cache.py` | LOW | Ambiguous class-level `_db` annotation |
| `utils.py` | LOW | Fragile `retry_async` factory closure pattern |

---

## Recommendations (Priority Order)

1. **Immediately:** Remove or replace fake token addresses in `config.py` ALLOWLIST. At minimum, remove all tokens beyond the top-20 well-established BEP-20 tokens (BNB, USDT, USDC, BUSD, BTCB, ETH, CAKE, XRP, LINK, DOT, ADA, DOGE, TRX, AVAX, MATIC, SHIB, LTC, UNI, BCH, ATOM).
2. **Immediately:** Wrap all `quoter.py` blocking calls in `run_in_executor`. This is blocking the entire async event loop on every cycle.
3. **Soon:** Fix the `log.py` transaction rollback issue to prevent unlogged live trades.
4. **Soon:** Fix the shutdown race in `agent.py`.
5. **Soon:** Add `update_cash()` to portfolio and persist cash at end of each cycle.
6. **Soon:** Remove password from TWAK command-line logging or pass via environment variable.
7. **Nice-to-have:** Add checksum validation at startup for all ALLOWLIST addresses.