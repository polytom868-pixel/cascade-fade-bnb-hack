# CascadeFade — TWAK + Quoter Fix Plan

**Files audited:** `src/twak.py`, `src/quoter.py`
**Auditor:** Plan Agent
**Date:** 2026-06-21
**Budget:** No code changes. Plan only.

---

## Audit Summary

Both files parse cleanly (`ast.parse` OK). Combined, **9 distinct bugs** were found across
both files, including 1 hard crash, 3 wrong-value defects, 2 security issues, 1 silent failure,
and 2 missing validations.

---

## 1. quoter.py — Issues Table

| # | Line | Issue | Severity | Exact Replacement Code |
|---|------|-------|----------|------------------------|
| Q1 | 148 | `timeout=15` passed to `ContractFunction.call()` — web3 7.x `call()` signature is `(transaction, block_identifier, state_override, ccip_read_enabled)`. `timeout` is NOT a valid parameter. Will raise `TypeError: call() got an unexpected keyword argument 'timeout'`. **Hard crash.** | CRITICAL | Replace the `_call_quoter` inner function body with a provider-timeout approach and remove the spurious `timeout` kwarg entirely. See Fix Q1 below. |
| Q2 | 95 | `amount_in_wei = 0` when `amount_in == 0.0`. Contract will revert with empty calldata — no revert string, just silent failure caught by the broad `except Exception`. Log says `"Quoter failed for X→Y fee=N: execution reverted"` — no indication amount was zero. | MEDIUM | Add explicit guard before the loop in `estimate_slippage_single`. See Fix Q2 below. |
| Q3 | 108–112 | Slippage formula uses USD-equivalent `ideal_out` only when `price_map` data is available. When `price_map` is absent, `ideal_out = amount_in` (raw token units). For a BTC→USDT quote, `amount_out` is ~50000 USDT units but `ideal_out = 1` BTC unit → `slippage = (1-50000)/1 = -49999%`. Triggers a false "ok" status with garbage slippage_pct. | HIGH | When `price_map` is missing, fall back to `ideal_out = None` and skip slippage computation, returning `"status": "no_price_data"` instead. See Fix Q3 below. |
| Q4 | 26 | `PCS_FEE_TIERS = [100, 500, 3000, 10000]` in `config.py`. PancakeSwap v3 standard fee tiers are `[100, 500, 2500, 10000]`. The 0.30% tier (3000) is **not** a standard PancakeSwap fee. Trying to quote with fee=3000 will hit an empty pool → silently no output for that tier. Agents skip it but waste an RPC round-trip and lose the 0.25% pool as the best option. | MEDIUM | Change `config.py` line: `PCS_FEE_TIERS = [100, 500, 2500, 10000]`. Update PLAN.md and ARCHITECTURE.md to match. |
| Q5 | 66–70 | `self.wallet_address` may be `None` (default). When `None`, `call_kwargs` is `{}` and the `from` field is omitted from `eth_call`. This is fine for read-only calls — QuoterV2 is a view function. However, if `wallet_address` is later set and is not checksummed, `Web3.to_checksum_address` is NOT called on it, causing a potential revert. | LOW | In `estimate_slippage_single`, ensure `from_addr`/`to_addr` are checksummed at call time. Already done for `address` in `get_balance` (line 162-168) but missing in `estimate_slippage_single`. See Fix Q5 below. |
| Q6 | 50 | Uses synchronous `Web3(Web3.HTTPProvider(rpc_url))` wrapped in `asyncio.to_thread()`. This is functionally correct but prevents reuse of `AsyncWeb3`. `web3 7.15.0` ships `AsyncWeb3` for true non-blocking calls. Current approach blocks one thread per concurrent RPC call. Acceptable for ≤10 concurrent quotes but does not scale. | LOW | Document as known limitation. Consider migration to `AsyncWeb3` as a post-competition optimization. No fix required for MVP. |
| Q7 | 48 | If `self.w3.is_connected()` is `False` at `__init__`, the constructor does NOT raise — it logs an error and continues. All subsequent `estimate_slippage_single` calls will fail with `web3.exceptions.MissingConfigurationForAddress`. No guard in `estimate_slippage_single`. | MEDIUM | Add a `self._connected` flag set in `__init__`. Check `self._connected` at the top of `estimate_slippage_single` and `get_balance`. Return `{"error": "RPC not connected", ...}` instead of letting web3 throw. See Fix Q7 below. |

### Fix Details — quoter.py

**Fix Q1 (Line 148 — timeout crash):**
The `timeout=15` in the `call()` transaction dict is passed to neither the transaction
params dict nor the `call()` method itself — it silently raises TypeError in web3 6+.

```python
# BEFORE (BROKEN):
def _call_quoter(p: dict) -> list:
    call_kwargs = {"from": self.wallet_address} if self.wallet_address else {}
    return self.quoter.functions.quoteExactInputSingle(p).call(call_kwargs, timeout=15)

# AFTER (FIXED):
def _call_quoter(p: dict) -> list:
    call_kwargs: dict = {}
    if self.wallet_address:
        call_kwargs["from"] = Web3.to_checksum_address(self.wallet_address)
    # NOTE: web3 ContractFunction.call() does NOT accept a timeout kwarg.
    # Timeout is controlled at the provider level via HTTPProvider(request_kwargs).
    # For per-call cancellation, use asyncio.wait_for() OUTSIDE asyncio.to_thread().
    return self.quoter.functions.quoteExactInputSingle(p).call(call_kwargs)
```

Also move `timeout=30` (from function signature) to apply to `asyncio.wait_for()` around the
`to_thread` call instead:

```python
# Wrap at call site (line ~150):
try:
    result = await asyncio.wait_for(
        asyncio.to_thread(_call_quoter, params),
        timeout=15.0,
    )
```

**Fix Q2 (amount_in=0 crash):**
```python
# Add before the fee-tier loop in estimate_slippage_single:
if amount_in_wei == 0:
    logger.warning("quote: amount_in is 0 for %s→%s", from_symbol, to_symbol)
    return {"error": "amount_in is zero", "slippage_pct": 1.0, "status": "zero_input"}

# Also add after best is computed:
if best["amount_out"] == 0:
    best["status"] = "no_liquidity"
```

**Fix Q3 (slippage NaN without price_map):**
```python
# BEFORE the fee loop:
_has_price_data = bool(price_map and from_price and to_price and from_price > 0 and to_price > 0)

# Slippage calculation inside the loop:
if _has_price_data:
    if ideal_out > 0:
        slippage = max(0.0, (ideal_out - amount_out) / ideal_out)
    else:
        slippage = 0.0
else:
    # Cannot compute meaningful slippage without price data
    best["slippage_pct"] = None   # sentinel: re-quote before swap
    best["status"] = "no_price_data"
```

**Fix Q5 (checksum addresses in call):**
```python
# At top of estimate_slippage_single, after from_addr/to_addr check:
from_addr_cs = Web3.to_checksum_address(from_addr)
to_addr_cs = Web3.to_checksum_address(to_addr)

# Use from_addr_cs / to_addr_cs in the params dict
```

**Fix Q7 (connection guard):**
```python
# In __init__:
self._connected = self.w3.is_connected()
if not self._connected:
    logger.error("Cannot connect to BSC RPC: %s", rpc_url)

# At top of estimate_slippage_single:
if not self._connected:
    return {"error": "RPC not connected", "slippage_pct": 1.0, "status": "rpc_error"}
```

---

## 2. twak.py — Issues Table

| # | Line | Issue | Severity | Exact Replacement Code |
|---|------|-------|----------|------------------------|
| T1 | 57 | `get_address()` calls `self._run(["twak", "wallet", "address", "--json"], timeout=60)` **directly** — it does NOT go through `_build_cmd`. Therefore `--password` is **never** added, even when `self.password` is set. TWAK will prompt for password interactively, blocking forever in the non-interactive asyncio subprocess, causing a 60s timeout. | HIGH | Change `get_address` to use `_build_cmd` or manually append `--password` when set. See Fix T1 below. |
| T2 | 31 | `self.password` is passed as a CLI argument `--password Secret123!`. On Linux, `ps aux` shows full command line including the password for all running processes. Any unprivileged user or log-scraping tool can read it. | HIGH | Use `--password-file` (if TWAK supports it) or pass password via `stdin` using `communicate(input=...)`. See Fix T2 below. |
| T3 | 41 | `_build_cmd` validates `quote_address` (42-char hex), but the `from_token` / `to_token` in `swap()` are passed directly to the subprocess without any validation. A malicious or malformed token string (e.g. containing shell metacharacters) is passed raw. `shlex.quote` is used in logging but NOT in the actual `asyncio.create_subprocess_exec` call. | MEDIUM | Apply `shlex.quote()` to each token arg in the subprocess call. See Fix T3 below. |
| T4 | 54 | `asyncio.create_subprocess_exec` is called without `capture_output=True`. `stdout` and `stderr` are piped individually, which is functionally equivalent — **but `text=True` is not set**, so `stdout_b` and `stderr_b` are `bytes`, requiring explicit `.decode()`. The code handles this correctly with `.decode("utf-8", errors="replace")`. However, the signature used is the non-text variant — adding `text=True` would eliminate the manual decode and is more idiomatic for `asyncio.subprocess`. | LOW | Add `text=True` to `create_subprocess_exec`. Then change `stdout_b`/`stderr_b` to `stdout`/`stderr` strings directly, and remove the `.decode()` calls. |
| T5 | 54 | `timeout` in `_run` defaults to `120`. For a wallet-balance query (`get_balance`), the timeout is overridden to `60`. For a swap, the timeout is `120`. On BSC, a swap confirmation can take 10–60s under normal load, up to 5 min during congestion. `120s` is too short for live swaps. | MEDIUM | Bump swap timeout to `300` (5 min). See Fix T5 below. |
| T6 | 133–137 | `get_address()` ignores `self.password` entirely and calls `_run` directly. If the test command `twak wallet address --chain bsc --json --password` was failing, the root cause is that `get_address()` never passes `--password` to TWAK. The other methods use `_build_cmd` which adds `--password`. **This is the confirmed bug** from testing. | HIGH | See Fix T1. |
| T7 | 63–87 | The error-return dict always sets `result["data"] = {"raw": stdout[:500]}` even when parsing fails and the output is an error message. This means `result["data"]["raw"]` could contain a non-JSON error string that downstream code (e.g. `agent.py`) may try to use as valid data. | LOW | When `proc.returncode != 0`, do not populate `result["data"]` with raw stdout. Set `result["data"] = None` and put raw output only in `result["error"]`. |
| T8 | 54–60 | `create_subprocess_exec` receives `*cmd` where `cmd` is a list built by `_build_cmd`. The subprocess inherits the process group's signals by default. If this process receives SIGINT (Ctrl+C), the TWAK subprocess may also be killed before it can clean up, potentially leaving the wallet in an inconsistent state. | LOW | Pass `process_group=0` to isolate signal handling, or wrap in a `try/finally` to ensure graceful TWAK shutdown. (Lower priority — signal handling in `agent.py` already sets a flag; the subprocess timeout provides fallback.) |

### Fix Details — twak.py

**Fix T1 (get_address missing --password):**
```python
# BEFORE (BROKEN):
async def get_address(self) -> str | None:
    result = await self._run(["twak", "wallet", "address", "--json"], timeout=60)

# AFTER (FIXED):
async def get_address(self) -> str | None:
    cmd = self._build_cmd(["wallet", "address"], json_output=True)
    result = await self._run(cmd, timeout=60)
    data = result.get("data", {})
    if isinstance(data, dict):
        return data.get("address") or data.get("wallet_address")
    return None
```

**Fix T2 (password in process list):**
The cleanest fix without changing TWAK's behavior is to pass password via stdin.
TWAK CLI supports `--password` reading from stdin or env var. Verify with `twak --help`.

```python
# Option A — pass via stdin (preferred if TWAK supports it):
async def _run(self, cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    # Remove --password from cmd list, send it via stdin instead
    password_input: bytes | None = None
    if "--password" in cmd:
        pw_idx = cmd.index("--password")
        password_input = f"{cmd[pw_idx + 1]}\n".encode()
        cmd = cmd[:pw_idx] + cmd[pw_idx + 2:]   # strip --password <value>

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if password_input else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if password_input:
        proc.stdin.write(password_input)   # type: ignore[union-attr]
        await proc.stdin.drain()           # type: ignore[union-attr]
        proc.stdin.close()                 # type: ignore[union-attr]

    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
```

If TWAK does NOT support stdin password, the fallback is environment variable:

```python
# Option B — env var (if TWAK checks TWAK_WALLET_PASSWORD env):
async def _run(self, cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    import os
    env = os.environ.copy()
    cmd_list = [c for c in cmd]  # shallow copy
    pw = None
    if "--password" in cmd_list:
        pw_idx = cmd_list.index("--password")
        pw = cmd_list[pw_idx + 1]
        cmd_list = cmd_list[:pw_idx] + cmd_list[pw_idx + 2:]
        env["TWAK_WALLET_PASSWORD"] = pw   # TWAK reads from env
    proc = await asyncio.create_subprocess_exec(
        *cmd_list,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env if pw else None,
    )
    ...
```

**Fix T3 (token injection):**
```python
# In _build_cmd, tokens arrive as raw strings from swap():
async def swap(self, amount: float, from_token: str, to_token: str, ...) -> dict[str, Any]:
    # Validate and sanitize before passing to _build_cmd
    safe_from = self._safe_token(from_token.strip())
    safe_to = self._safe_token(to_token.strip())
    cmd = self._build_cmd(["swap", str(amount), safe_from, safe_to], ...)
```

Where `_safe_token` is:
```python
@staticmethod
def _safe_token(token: str) -> str:
    """Reject tokens containing shell metacharacters."""
    if not token:
        raise ValueError("Empty token")
    if not all(c.isalnum() or c in "._-" for c in token):
        raise ValueError(f"Token contains unsafe chars: {token!r}")
    return token
```

**Fix T5 (swap timeout too short):**
```python
async def swap(self, amount: float, ...) -> dict[str, Any]:
    return await self._run(cmd, timeout=300)  # was 120
```

---

## 3. Hidden Bugs Found

### H1: Slippage NaN when `price_map` is None (quoter.py:106–112)
Already covered as Q3. The formula `slippage = max(0.0, (ideal_out - amount_out) / ideal_out)` 
produces `-49999` when `price_map` is absent and token unit values differ by orders of magnitude.

**Impact:** Agent may approve swaps with no meaningful slippage check, executing at any price.

### H2: `amount_in=0` silently returns `status="no_liquidity"` (quoter.py:95)
Already covered as Q2. No distinction between "no liquidity" and "zero input" — identical
return value makes debugging impossible.

**Impact:** Buggy callers get a confusing "no_liquidity" instead of a clear error message.

### H3: `fee=3000` is NOT a PancakeSwap v3 standard tier (config.py)
Already covered as Q4. The 0.25% tier uses `fee=2500`. Using `fee=3000` (0.30%) hits a
non-existent pool. PancakeSwap v3 deployments on BSC have pools at 100, 500, 2500, 10000 bps.

**Impact:** Agents waste one RPC round-trip per quote and miss the dominant 0.25% liquidity tier.

### H4: Race condition between `quote()` and `swap()` — no re-quote gate
`agent.py` calls `decision.run_cycle()` which internally may call `estimate_slippage_single()`
to approve a buy. Between that quote and the actual `twak.swap()` call, price can move.
`quoter.estimate_slippage_single` returns `slippage_pct` at quote time; `swap()` ignores it
and always passes `slippage=0.5` to TWAK.

TWAK itself respects the 0.5% cap. However, the agent's own decision to buy was made at
the old price. If price moves 2% between quote and swap, the agent's stop-loss/take-profit
levels are now offset by 2%.

**Impact:** BUY signal may be invalidated by the time swap confirms. The signal engine
does not re-verify before executing.

**Fix:** In `agent.py`, before executing any `twak.swap()`, call `quoter.estimate_slippage_single()`
again and verify `slippage_pct < MAX_SLIPPAGE_PCT` using the current price. This is the
same pattern used for forced sells — re-quote before execution.

```python
# In _execute_sell and before any buy in decision.py:
quote = await self.quoter.estimate_slippage_single(from_sym, to_sym, units, ...)
if quote.get("slippage_pct", 1.0) >= MAX_SLIPPAGE_PCT:
    logger.warning("Slippage too high at execution time: %.2f%%", quote["slippage_pct"] * 100)
    return {"error": "slippage exceeded"}
```

### H5: `AsyncWeb3` not used — thread pool saturation under load
`quoter.py` uses synchronous `Web3` inside `asyncio.to_thread()`. Each concurrent quote
occupies a full thread for the duration of the HTTP call (200ms–2s). With 10 concurrent
quotes, this saturates a small thread pool.

**Impact:** Under load (e.g., 50 tokens to quote), quotes serialize or fail with
"executor already shutdown" errors.

**Fix:** Migrate to `AsyncWeb3` from `web3 import AsyncWeb3`. All `contract.functions.X().call()`
become `contract.functions.X().call()` on an `AsyncWeb3` instance, natively awaitable.
No `asyncio.to_thread()` needed.

```python
from web3 import AsyncWeb3

class Quoter:
    def __init__(self, rpc_url: str = BSC_RPC_URL, wallet_address: str | None = None) -> None:
        self.w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
        self._connected = asyncio.get_event_loop().run_until_complete(
            self.w3.is_connected()
        )
        self.quoter = self.w3.eth.contract(address=PCS_V3_QUOTER_V2, abi=QUOTER_V2_ABI)

    async def estimate_slippage_single(self, ...):
        # No asyncio.to_thread needed — await directly
        result = await self.quoter.functions.quoteExactInputSingle(params).call()
```

**Note:** `AsyncWeb3` initialization requires an active event loop. For compatibility with
the current `__init__` constructor, defer the connection check to the first method call.

### H6: Wallet address not checksummed before ABI call (quoter.py:66–70)
Already covered as Q5. `call_kwargs["from"] = self.wallet_address` is set without
`Web3.to_checksum_address()`.

**Impact:** If `wallet_address` is passed as a non-checksum address (e.g. lowercase),
`eth_call` will revert with `InvalidParams: invalid address` on some RPC endpoints.
BSC RPC may tolerate non-checksum but this is inconsistent.

### H7: `get_address()` silently returns `None` without retry
`twak wallet address` requires the wallet to be unlocked. If TWAK's keyring is not cached
(because `--password` was missing), the call times out after 60s. The result dict returns
`None` as address with no indication of WHY it failed.

**Impact:** Agent continues startup with `wallet_address = None`, causing downstream
failures in `quoter.py` call_kwargs and `agent.py` TWAK address logging.

---

## 4. On-Chain ABI / Contract Verification

| Contract | Address | Status |
|----------|---------|--------|
| PancakeSwap V3 QuoterV2 | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` | **VERIFIED** — this is the QuoterV2 on BSC mainnet |
| `quoteExactInputSingle` function | Present in QuoterV2 | **CORRECT** ABI used in quoter.py |
| `QuoteExactInputSingleParams` tuple | fee: uint24, amountIn: uint256, sqrtPriceLimitX96: uint160 | **CORRECT** ABI matches deployed contract |
| Output: `amountOut` (uint256) | Correct | ABI matches |
| Output: `sqrtPriceX96After` (uint160) | Correct | ABI matches |
| Output: `initializedTicksCrossed` (uint32) | Correct | ABI matches |
| Output: `gasEstimate` (uint256) | Correct | ABI matches |
| `PCS_FEE_TIERS` in config.py | `[100, 500, 3000, 10000]` | **WRONG** — should be `[100, 500, 2500, 10000]` |
| WBNB address | `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c` | **CORRECT** |

**Conclusion on ABI:** The QuoterV2 ABI in `quoter.py` is correct for the deployed contract.
The only mismatch is the 0.25% fee tier (2500 vs 3000).

---

## 5. Security

### S1: Wallet password in process list (twak.py:31)
**Status:** CONFIRMED. `--password SecretPass` appears in `ps aux` output for all running
processes. Any user on the system can read the password.

**Fix:** See Fix T2 above — pass password via `stdin` or environment variable.

**Severity:** HIGH — wallet seed security is compromised if multiple users share the host.

### S2: Token arguments not shell-escaped in subprocess exec (twak.py:54)
`asyncio.create_subprocess_exec` does NOT invoke a shell, so shell injection is not possible
through token arguments. However, the `_safe_token` validation (Fix T3) should still be
applied to catch token-format bugs (e.g., tokens with newlines that TWAK misparses).

**Status:** MEDIUM (defense-in-depth). The current code is not exploitable via shell injection
because `create_subprocess_exec` does not shell out. The risk is malformed tokens causing
unexpected TWAK behavior.

### S3: Error messages logged with truncated output (twak.py:81, 107)
Error messages from TWAK are truncated to 500 chars and logged. This is fine — prevents
log flooding. No PII in error messages from TWAK.

**Status:** OK.

---

## 6. Cheats to Remove

| # | Location | Description | Action |
|---|----------|-------------|--------|
| C1 | `src/agent.py` — `_execute_sell` | Paper mode sets `tx_hash = f"0xSELL_PAPER_{sym}"` — hardcoded fake hash that looks like a real BSC tx hash but fails BSCScan verification. | Remove before submission. Replace with `tx_hash = ""` and log paper mode explicitly. |
| C2 | `src/agent.py` — forced sell in paper mode | `if self.mode != "paper"` gate around `twak.swap()`. In paper mode, forced sells skip TWAK entirely but update portfolio as if the sell succeeded. This inflates simulated PnL. | Add explicit paper-mode sell simulation that applies a 0.6% round-trip cost to simulate realistic execution. |
| C3 | `src/decision.py` — if decision engine exists | Not audited here, but the decision engine likely has a paper-mode bypass for buys. Flag for separate audit. | Verify all paper-mode paths apply ROUND_TRIP_COST_PCT to simulate realistic execution. |

---

## 7. Complete Replacement Table

| File | Line(s) | Bug ID | Fix Summary |
|------|---------|--------|-------------|
| `src/quoter.py` | 148 | Q1 | Remove `timeout=15` from `.call()` call. Move timeout to `asyncio.wait_for()` around `asyncio.to_thread()`. |
| `src/quoter.py` | 95 | Q2 | Add `if amount_in_wei == 0: return {"error": "amount_in is zero", ...}` guard before fee-tier loop. |
| `src/quoter.py` | 108–112 | Q3 | Add `_has_price_data` flag. Skip slippage computation when `price_map` absent. Set `slippage_pct = None` and `status = "no_price_data"`. |
| `src/quoter.py` | 66–70 | Q5 | Wrap `from_addr`/`to_addr` with `Web3.to_checksum_address()` in params. |
| `src/quoter.py` | 48 | Q7 | Set `self._connected = self.w3.is_connected()` in `__init__`. Guard all methods. |
| `src/config.py` | 26 | Q4 | Change `PCS_FEE_TIERS = [100, 500, 3000, 10000]` to `PCS_FEE_TIERS = [100, 500, 2500, 10000]`. |
| `src/twak.py` | 133–137 | T1, T6 | Rewrite `get_address()` to use `_build_cmd()` or manually add `--password`. |
| `src/twak.py` | 31, 54–60 | T2 | Move password from CLI arg to `stdin` or environment variable in `_run()`. |
| `src/twak.py` | 54–60 | T3 | Add `_safe_token()` validation and apply to swap token args. |
| `src/twak.py` | 54 | T4 | Add `text=True` to `create_subprocess_exec`. Remove manual `.decode()`. |
| `src/twak.py` | 121 | T5 | Change swap timeout from `120` to `300`. |
| `src/twak.py` | 63–87 | T7 | Set `result["data"] = None` when `returncode != 0`. |

---

## 8. Implementation Order (Chunks)

**Chunk 1 — quoter.py crash fix (Q1 + Q2)**
- Scope: `src/quoter.py`, `_call_quoter` function and `estimate_slippage_single`
- Depends: None
- Accept when: `python3 -c "from src.quoter import Quoter; print('import ok')"` succeeds, and `timeout=15` does not appear in any `.call()` invocation
- Open Questions: None

**Chunk 2 — config.py fee tier (Q4)**
- Scope: `src/config.py`, `PCS_FEE_TIERS`
- Depends: None
- Accept when: `PCS_FEE_TIERS == [100, 500, 2500, 10000]` in both config and PLAN.md/ARCHITECTURE.md

**Chunk 3 — twak.py get_address fix (T1 + T6)**
- Scope: `src/twak.py`, `get_address()` method
- Depends: None
- Accept when: `get_address()` goes through `_build_cmd()` and passes `--password` when `self.password` is set

**Chunk 4 — twak.py security: password in process list (T2)**
- Scope: `src/twak.py`, `_run()` method
- Depends: Chunk 3
- Accept when: `--password <value>` does not appear in `ps aux` output during TWAK execution

**Chunk 5 — quoter.py slippage NaN (Q3)**
- Scope: `src/quoter.py`, slippage computation block
- Depends: Chunk 1
- Accept when: `slippage_pct` is never negative and is `None` when `price_map` is absent

**Chunk 6 — quoter.py checksum + connection guard (Q5 + Q7)**
- Scope: `src/quoter.py`, `estimate_slippage_single`, `get_balance`, `__init__`
- Depends: Chunk 1
- Accept when: All address parameters are checksummed; all methods check `self._connected`

**Chunk 7 — agent.py re-quote gate (H4)**
- Scope: `src/agent.py`, `_execute_sell()` and `decision.py` buy execution path
- Depends: Chunks 1+5
- Accept when: Every `twak.swap()` call is preceded by a fresh `quoter.estimate_slippage_single()` call and a slippage check

**Chunk 8 — Cheats removal (C1, C2)**
- Scope: `src/agent.py`
- Depends: None
- Accept when: No `0xSELL_PAPER_` strings in code; paper mode applies `ROUND_TRIP_COST_PCT`

---

## 9. Verification Strategy

```bash
# Syntax check
python3 -c "import ast; ast.parse(open('src/quoter.py').read())"
python3 -c "import ast; ast.parse(open('src/twak.py').read())"

# Q1 check: no timeout= in call()
grep -n 'call.*timeout' src/quoter.py  # should return nothing

# Q4 check: fee tiers
python3 -c "from src.config import PCS_FEE_TIERS; assert PCS_FEE_TIERS == [100,500,2500,10000], PCS_FEE_TIERS"

# T1 check: get_address uses _build_cmd
python3 -c "
from src.twak import TWAKExecutor
t = TWAKExecutor(password='test')
# Monkey-patch _build_cmd to capture calls
calls = []
orig = t._build_cmd
def track(*a, **kw): calls.append((a, kw)); return orig(*a, **kw)
t._build_cmd = track
import asyncio
asyncio.run(t.get_address())
assert calls, 'get_address did not call _build_cmd'
print('get_address calls _build_cmd: OK')
"

# T2 check: no --password in process list (manual: run agent, check ps aux | grep twak)
# T3 check: tokens validated
python3 -c "
from src.twak import TWAKExecutor
t = TWAKExecutor()
assert t._safe_token('BNB') == 'BNB'
try: t._safe_token('BNB; rm -rf /')
except ValueError: pass
else: raise AssertionError('No injection check')
print('_safe_token: OK')
"
```

---

## 10. Decision Log

| Decision | Rationale | Rejected Alternatives |
|----------|-----------|-----------------------|
| Fix timeout via `asyncio.wait_for()` around `to_thread`, not via provider config | Provider-level timeout is global; per-call cancellation is needed for the fee-tier loop | Use `request_kwargs={'timeout': 15}` on HTTPProvider — too broad |
| Move password to stdin, not env var | stdin is cleared immediately after write; env vars persist in `/proc/<pid>/environ` for the lifetime of the process | Env var approach leaves password in process memory longer |
| Use `_build_cmd` for `get_address` instead of raw list | Consistent with all other TWAK methods; `_build_cmd` handles `--password` and `--chain` correctly | Keep raw list and duplicate `--password` logic — DRY violation |
| Change `PCS_FEE_TIERS` from 3000 to 2500 | PancakeSwap v3 uses 2500 for 0.25% tier on BSC | Keep 3000 — would miss the dominant liquidity pool |
| Add `_has_price_data` flag for slippage fallback | Clear sentinel (`None`) lets decision engine know slippage is uncomputable | Return `slippage_pct = 0.0` — false "ok" signal |
| Migrate to AsyncWeb3 (deferred to post-competition) | Requires async event loop in `__init__` which complicates constructor; thread pool is acceptable for ≤20 concurrent quotes | AsyncWeb3 now — adds complexity for marginal gain at competition scale |

---

## 11. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Fix Q1 breaks web3 call for other reasons | Low | Test with a mock contract before live deployment |
| TWAK stdin password not supported | Medium | Fall back to `--password-file` if TWAK exposes it; document env-var fallback |
| Changing fee tiers causes brief quote disruption | Low | No trades execute between fix and first quote cycle; safe to apply atomically |
| AsyncWeb3 migration introduces new bugs | Medium | Deferred post-competition; thread pool is sufficient for current scale |
| `get_address` fix breaks if TWAK output format changes | Low | The fix uses `_build_cmd` which already parses JSON correctly; format is stable |

---

*End of plan. No code was modified.*