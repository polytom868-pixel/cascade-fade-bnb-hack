# Audit Report: CascadeFade SUBMISSION.md vs Codebase

**Auditor:** Review Agent
**Date:** 2026-06-20
**Files reviewed:** SUBMISSION.md, src/*.py, tests/test_risk.py, PLAN.md, AGENTS.md, README.md, ARCHITECTURE.md, POLICY.md, run.sh

---

## Verdict: NEEDS_FIXES

The submission contains one critical factual error (the 149-token allowlist claim), several items that are partially backed by working code, and several checklist items that are confirmed or not yet verifiable at submission time.

---

## Rules Verification Table — Claim by Claim

### 1. "Public GitHub repo"
**Status: FALSE (at time of review)**

There is no evidence that the repo was made public. All checklist items in SUBMISSION.md's "Hard Constraints Checklist" remain unchecked (`[ ]`). The repo may be intended to go public before submission, but as of the current codebase state, there is no verification that a public GitHub repo exists with a valid URL submitted to DoraHacks.

---

### 2. "Demo video (3 min)" — SUBMISSION.md marks as ⏳
**Status: UNVERIFIABLE (pending)**

No video file, URL, or artifact exists in the codebase. This is correctly marked as pending.

---

### 3. "Track 1 submission before June 21 12:00 UTC" — marks as ⏳
**Status: UNVERIFIABLE (pending)**

No evidence of DoraHacks form submission timestamp exists in the codebase.

---

### 4. "On-chain registration before June 22" — marks as ⏳
**Status: UNVERIFIABLE (pending)**

The `twak.py` executor has a `compete_register()` method that calls `twak compete register --chain bsc --json`. However, there is no evidence of a completed BSCScan transaction for contract `0x212c61b9b72c95d95bf29cf032f5e5635629aed5`. This is correctly marked as pending.

---

### 5. "Trades on BSC during June 22–28" — marks as ⏳
**Status: UNVERIFIABLE (pending — future event)**

The infrastructure is in place, but actual trading has not occurred yet.

---

### 6. "149-token BEP-20 allowlist — Hardcoded in `src/config.py`"
**Status: FALSE**

The `ALLOWLIST` in `src/config.py` contains exactly **50 tokens**, not 149. The code itself contains a TODO comment explicitly acknowledging this:

```python
# ── 149-token allowlist (placeholder — top 50 BEP-20 tokens) ─────────────
# TODO: Replace with official 149-token list before trading window.
```

Evidence:
```
$ python3 -c "from src.config import ALLOWLIST; print(len(ALLOWLIST))"
50
```

The SUBMISSION.md "Rules Verification" table claims "149-token allowlist" with status "✅ (top 50; updating for 149)". This is misleading. The claim should be marked FALSE or at minimum PARTIAL with a clear TODO note. The parenthetical "(top 50; updating for 149)" is an internal caveat not visible to a competition judge reading only the top-level status column.

**Fix required:** Either (a) hardcode all 149 tokens from the official competition list (if available from the organizer), or (b) change the claim to accurately reflect "50-token allowlist (top BEP-20 by mktcap), TODO: expand to 149 before window."

---

### 7. "≥1 trade/day — Signal + heartbeat guarantees one/day"
**Status: ✅ TRUE**

Heartbeat logic is implemented in `src/risk.py` → `RiskManager.check_heartbeat()` and `select_heartbeat_pair()`. The method triggers a heartbeat trade if:
- No trade has occurred in the last 22 hours, OR
- Current UTC hour matches `HEARTBEAT_HOUR_UTC` (20:00)

The test `test_heartbeat()` in `tests/test_risk.py` passes:
```
✅ test_heartbeat passed
```

The heartbeat is wired into the main loop via `src/decision.py` (lines 103-118).

Note: The claim "≥1 trade/day" is guaranteed by the heartbeat. Whether this meets the competition's definition of a qualifying trade depends on the competition rules interpretation of "trade."

---

### 8. "Portfolio > $1 at each hour — Internal stop at $5, never approaches $1"
**Status: ✅ TRUE**

`PORTFOLIO_FLOOR_USD = 5.0` is hardcoded in `src/config.py`. The `RiskManager.check_portfolio_floor()` in `src/risk.py` enforces a stop when portfolio < $5. The test `test_portfolio_floor()` passes:

```
FLOOR BREACH: 4.99 < 5.00 — stopping new entries
✅ test_portfolio_floor passed
```

This correctly exceeds the implied $1 minimum with a 5x safety buffer.

---

### 9. "No token launches/airdrops"
**Status: ✅ TRUE**

The codebase contains **zero code** that deploys, mints, creates, or airdrops tokens. The execution layer (`src/twak.py`) only calls `twak swap` for existing BEP-20 token swaps. No contract deployment, no ERC-20 creation, no mint functions exist anywhere in `src/`.

`POLICY.md` explicitly documents: "No new token deployments: Agent does not deploy, mint, list, or create any token."

---

### 10. "Real on-chain PnL — BSCScan wallet history is source of truth"
**Status: ✅ TRUE (with caveat)**

The code correctly establishes BSCScan as the authoritative PnL source, and the trade journal logs every tx hash. However:

- There is **no active BSCScan API integration** in the code. The claim "BSCScan wallet history is source of truth" means the judge should manually look up the wallet on BSCScan — the agent does not push PnL data to BSCScan.
- There is no `bscscan.com` URL anywhere in the codebase linking to the actual registered wallet address.
- The `COMPETITION_CONTRACT` address is defined in `config.py` but the actual registered wallet address that will be used is **never exposed** in any doc — it is only retrieved dynamically via `twak wallet address` at runtime.

This is a transparency gap: the SUBMISSION.md should include the **actual BSCScan wallet URL** (e.g., `https://bscscan.com/address/0x...`) so judges can verify. At review time, the wallet address is unknown (it's created at runtime by TWAK).

---

## Hard Constraints Checklist — Claim by Claim

| Item | Code Evidence | Verdict |
|---|---|---|
| Wallet registered and funded before June 22 | `twak.py` has `compete_register()` method; no completed tx in codebase | ⏳ PENDING |
| 149-token allowlist enforced | `ALLOWLIST` has 50 tokens, not 149 | ❌ FALSE |
| Heartbeat trade guarantees ≥1 trade/day | Implemented in `risk.py` + tested | ✅ TRUE |
| 25% drawdown hard stop in code and tested | `MAX_DRAWDOWN_PCT=0.25` in `risk.py` + test passes | ✅ TRUE |
| $5 portfolio floor in code and tested | `PORTFOLIO_FLOOR_USD=5.0` in `risk.py` + test passes | ✅ TRUE |
| MEV Guard RPC configured | `BSC_RPC_URL = "https://bscrpc.pancakeswap.finance"` in `config.py` | ✅ TRUE |
| No perp logic in code path | Grep returned zero matches for `perp`, `orderly`, `aster`, `short_position`, `_short` | ✅ TRUE |
| No ERC-8183 PnL ledger claims | Grep returned zero matches for `ERC-8183` in src/ | ✅ TRUE |
| No BNB x402 claims | Grep confirmed no BNB x402 claims in src/; README/SUBMISSION accurately state USDC on Base for CMC x402 | ✅ TRUE |
| Submission by June 21 10:00 UTC | No timestamp evidence in codebase | ⏳ PENDING |
| Demo video public | No video URL in codebase | ⏳ PENDING |
| Repo public | No GitHub URL evidence in codebase | ⏳ PENDING |
| 2+ hour paper run completed | No SQLite DB evidence in codebase (logs/ is gitignored) | ⏳ PENDING |
| Live test swap confirmed on BSCScan | No tx hash in codebase | ⏳ PENDING |

---

## Specific Bug Discrepancies

### BUG 1: ALLOWLIST count mismatch (Critical)
**File:** `src/config.py`, line `ALLOWLIST = {`  
**Problem:** Comment says "149-token allowlist" but the dict has exactly 50 entries.  
**Impact:** If a token outside the 50 is the ONLY token on the official 149-token list that has a buy signal, the agent would skip it (correct behavior) but if the agent needs to trade a token that is on the official list but NOT in the current 50, it would fail silently. The allowlist correctly prevents out-of-list trades, but the size claim is factually false.  
**Fix:** Either expand to 149 tokens, or change all documentation to say "50-token allowlist (subset pending official 149-token list)."

### BUG 2: Wallet address not documented
**File:** Multiple docs  
**Problem:** The registered TWAK wallet address — the single most important piece of evidence for PnL verification — is never printed to any file or documented in any markdown. It only exists at runtime via `twak wallet address`.  
**Impact:** Judges cannot look up the wallet on BSCScan without the address being published.  
**Fix:** `agent.py` should log the wallet address to `logs/wallet_address.txt` on startup, and this file should be referenced in SUBMISSION.md with the actual BSCScan URL.

### BUG 3: RAY contract address is PancakeSwap Router, not RAY token
**File:** `src/config.py` line `"RAY": "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4"`  
**Problem:** Address `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4` is the PancakeSwap V3 Smart Router, NOT the RAY (Raydium) token. If the agent ever executes a swap involving RAY using this address, it would fail or use the wrong contract.  
**Note:** RAY (Raydium) is a Solana token, not a BEP-20 token, so RAY should not be in the BEP-20 allowlist at all.  
**Fix:** Remove RAY from the allowlist, or replace with the correct Raydium BEP-20 address if one exists.

### BUG 4: RAYDIUM contract address
**File:** `src/config.py` line `"RAYDIUM": "0x14f5AB83D0bd40E75C8222255bc855a974568Dd5"`  
**Problem:** This address is sequentially similar to the RAY entry and is likely also fabricated. Like RAY, Raydium is primarily a Solana DEX. There is no verified Raydium BEP-20 on BSC.  
**Fix:** Remove RAYDIUM from the allowlist.

### BUG 5: Multiple addresses are sequential placeholder addresses
**Files:** `src/config.py` entries for PYTH, JUP, RAY, RAYDIUM, BONK, PENGU, WIF, FLOKI, PEPE, MEME, MAGA, AI, AGI, AGIX, FET, OCEAN  
**Problem:** Many addresses in the second half of the allowlist follow the pattern `0x<seq>ABCD...` where `<seq>` increments by 1. Compare:
- PYTH: `0xD3c0A2C8F3d0e9aF3C5D6B4F8A9E3c2D1B0A4F7e`
- JUP:  `0x0231f9e4E44c4F338F9D24bE2A6C3f5E8A9D7C6B`
- RAY:  `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4`
- RAYDIUM: `0x14f5AB83D0bd40E75C8222255bc855a974568Dd5`
- BONK: `0x15f6AC83D0bd40E75C8222255bc855a974568Dd6`
- PENGU: `0x16f7BC83D0bd40E75C8222255bc855a974568Dd7`

These addresses appear to be placeholder/fabricated. The ones at the start (BNB, USDT, BTCB, ETH, CAKE, etc.) appear to be real verified BSC contract addresses. The later ones should be verified or removed.

**Fix:** Verify every address against a BSC block explorer. Remove or replace unverified addresses. This is a correctness issue — if the agent tries to swap using a wrong contract address, the swap would fail.

---

## Risk Tests Summary

All 5 tests pass:
```
✅ test_drawdown_kill passed
✅ test_portfolio_floor passed
✅ test_position_size passed
✅ test_pre_trade_checks passed
✅ test_heartbeat passed
🎉 All risk tests passed!
```

This confirms the core risk management layer is correctly implemented.

---

## Additional Observations

### Positive findings:
- Architecture is sound: single asyncio process, no Docker/Redis, runs locally.
- MEV Guard RPC correctly configured.
- TWAK CLI wrapper is comprehensive with proper error handling.
- SQLite WAL-mode journal schema is well-designed.
- `run.sh` properly handles tmux vs nohup fallback.
- No perp/leveraged/short code found — spot-only as claimed.
- No false ERC-8183 PnL claims.
- No false BNB x402 claims.
- `POLICY.md` is well-written and accurately reflects the code.
- The `AGENTS.md` file contains the critical "ALLOWLIST (CRITICAL MISSING)" note, correctly identifying the 50-token limitation.

### Items needing action before June 22:
1. Expand allowlist to all 149 tokens (or document the limitation prominently)
2. Verify all contract addresses in the allowlist against BSC block explorer
3. Publish the wallet address and BSCScan URL
4. Run a live test swap and record the tx hash
5. Complete the 2-hour paper run and commit the SQLite journal
6. Record and publish the demo video
7. Make the repo public and submit the DoraHacks form
8. Complete `twak compete register` and verify on BSCScan

---

## Summary Scorecard

| Claim | Status |
|---|---|
| 149-token allowlist | ❌ FALSE — only 50 tokens |
| ≥1 trade/day via heartbeat | ✅ TRUE |
| $5 portfolio floor | ✅ TRUE |
| 25% drawdown stop | ✅ TRUE |
| No token launches/mints | ✅ TRUE |
| No perp logic | ✅ TRUE |
| No ERC-8183 PnL claims | ✅ TRUE |
| No BNB x402 claims | ✅ TRUE |
| MEV Guard RPC | ✅ TRUE |
| Real BSCScan PnL | ✅ TRUE (but wallet address not yet published) |
| Risk tests pass | ✅ TRUE |
| Repo public | ⏳ PENDING |
| Registration done | ⏳ PENDING |
| Demo video | ⏳ PENDING |
| Paper run 2h | ⏳ PENDING |
| Live test swap | ⏳ PENDING |
| Submission form | ⏳ PENDING |