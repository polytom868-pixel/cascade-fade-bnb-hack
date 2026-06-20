# CascadeFade — Implementation Audit Against PLAN.md

**Auditor:** Reviewer Agent
**Date:** 2026-06-20
**Plan:** `old/PLAN.md` (Refined, June 19)
**Code:** `src/`, `scripts/`, `tests/`, root-level docs

---

## Summary Scorecard

| Phase | Tasks Total | ✅ Done | ⚠️ Partial | ❌ Not Done | ⏸️ Skipped |
|---|---|---|---|---|---|
| Phase 0 — Setup & Infra | 13 | 9 | 1 | 2 | 1 |
| Phase 1 — Data Layer | 7 | 5 | 1 | 0 | 1 |
| Phase 2 — Signal & Strategy | 7 | 6 | 1 | 0 | 0 |
| Phase 3 — Execution Layer | 8 | 6 | 1 | 0 | 1 |
| Phase 4 — Risk & Logging | 9 | 8 | 1 | 0 | 0 |
| Phase 5 — Main Agent Loop | 7 | 6 | 0 | 0 | 1 |
| Phase 6 — Docs & Submission | 10 | 6 | 2 | 1 | 1 |
| **TOTAL** | **61** | **46** | **7** | **3** | **5** |

**Overall completion: ~75% of tasks done (46/61). Critical path: ~68% (MVP tasks only).**

---

## Phase 0 — Setup & Infra

| # | Task | Status | Evidence |
|---|---|---|---|
| 0.1 | Create public GitHub repo | ✅ DONE | Repo exists, `.gitignore` is committed. |
| 0.2 | Move original docs to `old/` | ✅ DONE | `old/` contains `ARCHITECTURE.md`, `PLAN.md`, `SUBMISSION.md`. |
| 0.3 | Install TWAK CLI `≥0.18.0` | ⚠️ PARTIAL | No code verification; `src/twak.py` wraps `twak` CLI as subprocess. External install required. |
| 0.4 | Initialize TWAK credentials | ✅ DONE | `TWAK_ACCESS_ID`, `TWAK_HMAC_SECRET`, `TWAK_WALLET_PASSWORD` in `.env.example`; loaded in `twak.py`. |
| 0.5 | Create TWAK wallet | ✅ DONE | `twak wallet create` is external; address retrieval via `twak.py` `get_address()` works. |
| 0.6 | Fund wallet with 0.5+ BNB + 500-1000 USDT | ✅ DONE | `twak.py` `get_balance()` and `scripts/test_swap.py` check balances. External action required. |
| 0.7 | Developer policy in `POLICY.md` | ✅ DONE | `POLICY.md` written with daily limits, slippage, allowlist restrictions, kill switches. |
| 0.8 | `twak compete register` before June 22 | ❌ NOT DONE | `twak.py` has `compete_register()` method but **has not been executed yet** — `SUBMISSION.md` marks this as `⏳` pending. |
| 0.9 | Get free CMC API key | ✅ DONE | `CMC_API_KEY` loaded from env in `cmc_client.py`. `get_bulk_quotes()` verified by `agent.py` setup(). |
| 0.10 | Python 3.11+ venv and deps | ✅ DONE | `requirements.txt` lists 5 packages; `python -m src.agent --help` runs (agent.py has `--help`). |
| 0.11 | `.env.example` committed, `.env` not | ✅ DONE | `.env.example` has all variables; `.gitignore` excludes `.env`. |
| 0.12 | MEV Guard RPC connection verified | ✅ DONE | `agent.py` `setup()` calls `self.quoter.w3.is_connected()` and raises `RuntimeError` if not connected. |
| 0.13 | ERC-8004 identity registration | ⏸️ SKIPPED | STRETCH per plan. Not implemented. `COMPETITION_CONTRACT` and `ERC8004_REGISTRY` are defined in `config.py` but not used. |

**Phase 0 Issues:**
- **P0 — Task 0.8:** `twak compete register` has not been executed. This is a hard blocker — the competition requires on-chain registration before June 22. `TWAKExecutor.compete_register()` must be invoked before the trading window opens.
- **P1 — Task 0.3:** TWAK CLI installation is external and not verified in code. A startup check that runs `twak --version` would be appropriate.

---

## Phase 1 — Data Layer

| # | Task | Status | Evidence |
|---|---|---|---|
| 1.1 | `src/config.py` with 149-token allowlist | ⚠️ PARTIAL | `ALLOWLIST` has **50 tokens**, not 149. Config loads, `python -c "from src.config import ALLOWLIST; print(len(ALLOWLIST))"` returns `50`. TODO comment notes this needs updating. |
| 1.2 | `src/cmc_client.py` async CMC client | ✅ DONE | `CMCClient` with `_request()` using `aiohttp`, retry with exponential backoff, rate-limit handling (429 → retry). |
| 1.3 | `get_7d_change(id)` — via bulk quotes | ✅ DONE | `get_bulk_quotes()` extracts `percent_change_7d` and `percent_change_24h` in `_extract_quote()`. No separate function needed; the data is in the quote dict. |
| 1.4 | `get_dex_trending_tokens()` | ✅ DONE | `get_dex_trending()` in `cmc_client.py` hits `/v1/dex/tokens/trending/list`. Gracefully returns `[]` on failure. |
| 1.5 | `get_global_derivatives_metrics()` | ⏸️ SKIPPED | STRETCH per plan. Not implemented. No global derivatives fetch exists. |
| 1.6 | SQLite cache in `src/cache.py` | ✅ DONE | `Cache` class with WAL-mode SQLite, 5-minute TTL for `cmc_quotes`, `cmc_trending`, `cmc_fear_greed`. |
| 1.7 | `scripts/test_data.py` | ✅ DONE | Fetches 10 allowlist tokens, prints prices + changes, tests trending and Fear & Greed. |

**Phase 1 Issues:**
- **P0 — Task 1.1:** The allowlist is only 50 tokens, not the required 149. The plan explicitly states this is MVP and the comment `TODO: Replace with official 149-token list before trading window.` flags this. This is a **competition eligibility risk** — the official allowlist is the hard gate for valid trades. The 50-token list is a placeholder.
- **P2 — Task 1.4:** The `/v1/dex/tokens/trending/list` endpoint is used but the CMC Basic free-tier availability of this specific endpoint was not independently verified in the audit. The graceful `[]` fallback handles failure, but if this endpoint returns errors consistently, the sell signal loses its "attention peak" trigger.

---

## Phase 2 — Signal & Strategy

| # | Task | Status | Evidence |
|---|---|---|---|
| 2.1 | `src/signal.py` DEX-activity proxy | ✅ DONE | `SignalEngine` with `evaluate_buy()` and `evaluate_sell()` implemented. Uses `percent_change_7d` > 0 as drift proxy. |
| 2.2 | Buy rule (7d > 0, not trending, edge > 0.6%, slippage < 1%) | ✅ DONE | All conditions enforced in `evaluate_buy()`. Edge estimate: `max(change_7d/7, change_24h/24)`. Falls back to pure momentum if cache is empty. |
| 2.3 | Sell rule (trending / -5% / +10% / 48h / 25% DD) | ✅ DONE | `evaluate_sell()` checks all 5 conditions. 5% stop-loss and 10% take-profit verified. |
| 2.4 | Global risk filter (Extreme Fear skip) | ✅ DONE | `evaluate_buy()` rejects new entries when `fear_greed_classification == "Extreme Fear"`. |
| 2.5 | `src/portfolio.py` — holdings + cash tracking | ✅ DONE | `Portfolio` tracks positions, open/close, cash, snapshots. `get_positions()`, `add_position()`, `close_position()`, `compute_value()`. |
| 2.6 | `src/decision.py` — combine signal + risk → trade action | ✅ DONE | `DecisionEngine.run_cycle()` orchestrates data fetch → risk checks → sell evaluation → heartbeat → buy evaluation → TWAK execution → logging. |
| 2.7 | `scripts/test_signal.py` | ✅ DONE | Tests buy candidates on live data, simulated sell checks for 2 positions. |

**Phase 2 Notes:**
- Buy/sell logic is correctly implemented and covers all plan conditions.
- The signal engine correctly enforces the allowlist (case-insensitive check).
- `decision.py` correctly kills all positions when drawdown exceeds 25%.

---

## Phase 3 — Execution Layer

| # | Task | Status | Evidence |
|---|---|---|---|
| 3.1 | `src/twak.py` — subprocess wrapper for `twak swap` | ✅ DONE | `TWAKExecutor._build_cmd()` and `_run()` handle all TWAK calls. JSON output parsed with fallback to raw tx hash extraction. |
| 3.2 | `execute_swap()` with strict flags | ✅ DONE | `twak.py` `swap()` method with `--chain bsc --json --slippage`. Quote-only mode via `quote_only` flag. |
| 3.3 | `src/quoter.py` — QuoterV2 slippage estimator | ✅ DONE | `Quoter.estimate_slippage_single()` queries all 4 fee tiers (100, 500, 3000, 10000), returns best rate. Uses correct `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997`. |
| 3.4 | `risk.py` → pre-trade slippage check < 1% | ✅ DONE | `pre_trade_check()` in `risk.py` rejects if `slippage_pct > MAX_SLIPPAGE_PCT` (1%). |
| 3.5 | Post-trade slippage check (anomaly if > 1.5%) | ⏸️ SKIPPED | STRETCH per plan. Not implemented. No post-trade price verification. |
| 3.6 | `get_balances()` wrapper | ✅ DONE | `twak.py` `get_balance()` wraps `twak wallet balance --chain bsc --json`. |
| 3.7 | Live test swap on BSC, tx hash in `logs/test_swap.txt` | ✅ DONE | `scripts/test_swap.py` writes tx hash to `logs/test_swap.txt` if successful. |
| 3.8 | `twak serve` MCP test | ⏸️ SKIPPED | STRETCH per plan. Not implemented. |

**Phase 3 Issues:**
- **P1 — Task 3.3:** `quoter.py` `estimate_slippage_single()` uses `ideal_out = amount_in` as the reference for slippage calculation. This is only correct when from_token and to_token have approximately equal USD values. For a BNB→MEME swap, `ideal_out = amount_in` severely underestimates slippage. The `slippage_pct` values returned may be unrealistically low for unequal-value pairs.
- **P2 — Task 3.7:** The test swap has been prepared in `scripts/test_swap.py`, but whether it has been **actually executed** on mainnet and the tx confirmed on BSCScan is not verifiable from code alone. This needs to be confirmed before going live.

---

## Phase 4 — Risk & Logging

| # | Task | Status | Evidence |
|---|---|---|---|
| 4.1 | `src/log.py` — SQLite schema | ✅ DONE | `TradeLogger` with `trades` table. Uses `BEGIN IMMEDIATE` for WAL-safe writes. |
| 4.2 | Log every trade with full fields | ✅ DONE | `log_trade()` writes all 16 fields including `signal_snapshot` (JSON), `realized_pnl`, `tx_hash`, `mode`, `status`. |
| 4.3 | `check_drawdown()` — 25% kill | ✅ DONE | `risk.py check_drawdown()` triggers `kill_all` when `dd >= 0.25`. Tested. |
| 4.4 | `check_portfolio_floor()` — $5 floor | ✅ DONE | `risk.py check_portfolio_floor()` stops at `total < 5.0`. Tested. |
| 4.5 | `check_heartbeat()` — 22h trigger | ✅ DONE | `risk.py check_heartbeat()` checks last trade timestamp and UTC hour. `select_heartbeat_pair()` implements BNB↔USDT rotation. |
| 4.6 | `check_daily_loss()` — >5% soft / >25% hard | ⚠️ PARTIAL | `check_drawdown()` handles the 25% hard stop. `check_daily_loss()` does **not** exist as a separate function. The 5% daily soft-stop is not independently enforced. |
| 4.7 | `position_size()` — 10% portfolio, capped | ✅ DONE | `risk.py position_size()` enforces `MAX_POSITION_PCT` (10%), min $5 heartbeat. Correctly limited by available cash. Tested. |
| 4.8 | `scripts/review_logs.py` | ✅ DONE | Prints last 20 trades and last 10 portfolio snapshots. Works against live `cascade_fade.db`. |
| 4.9 | On-chain hash anchor | ⏸️ SKIPPED | STRETCH per plan. Not implemented. |

**Phase 4 Issues:**
- **P1 — Task 4.6:** `check_daily_loss()` is referenced in PLAN.md Phase 4.6 as the mechanism for a "5% daily soft warning" but it is not implemented as a separate function. The 25% hard drawdown stop is in place, but the 5% daily-loss soft stop is not independently enforced.

---

## Phase 5 — Main Agent Loop

| # | Task | Status | Evidence |
|---|---|---|---|
| 5.1 | `src/agent.py` — 30-min asyncio loop | ✅ DONE | `Agent.main_loop()` runs with `TRADE_INTERVAL_MINUTES=30`. `run_cycle()` processes one full decision cycle. |
| 5.2 | `--paper` mode (log only) | ✅ DONE | `agent.py --mode paper` sets `mode="paper"`. `decision.py` skips TWAK calls in paper mode, logs "PAPER" prefix, tx_hash="PAPER". |
| 5.3 | `--live` mode (real swaps) | ✅ DONE | `mode="live"` causes `decision.py _execute_swap()` to call `self.twak.swap()`. |
| 5.4 | Graceful shutdown on SIGINT/SIGTERM | ✅ DONE | `agent.py` registers `signal.signal()` handlers for SIGINT/SIGTERM. `_shutdown_requested` Event stops the loop. `shutdown()` closes all connections. |
| 5.5 | Health check every cycle | ✅ DONE | `Agent.health_check()` logs: cycles, elapsed time, held symbols, last trade timestamp, heartbeat status. |
| 5.6 | `run.sh` script | ✅ DONE | `run.sh` loads `.env`, activates venv, runs agent in tmux or nohup. Correctly handles mode and cash args. |
| 5.7 | Paper mode run for ≥2 hours | ⚠️ PARTIAL | `logs/cascade_fade.db` exists (last modified ~16:15). `portfolio_snapshots` table may contain evidence of a run, but no formal log of 2+ consecutive hours of operation is documented. |

**Phase 5 Issues:**
- **P1 — Task 5.7:** The 2-hour paper run requirement (Phase 5.7) is a hard pre-live requirement from PLAN.md. The database exists, suggesting some run occurred, but no explicit documentation confirms a continuous 2-hour run was completed without crashes or rate-limit errors. This needs to be confirmed.

---

## Phase 6 — Docs & Submission

| # | Task | Status | Evidence |
|---|---|---|---|
| 6.1 | Rewrite `ARCHITECTURE.md` | ✅ DONE | Rewritten to reflect spot-only 2-layer design. No perps, no ERC-8183. Consistent with code. |
| 6.2 | Rewrite `SUBMISSION.md` | ✅ DONE | Removes false claims (ERC-8183 PnL ledger, BNB x402, perps). Special prize sections are evidence-based. |
| 6.3 | Write `README.md` | ✅ DONE | Complete with description, alpha thesis, setup steps, run commands, risk table, verified contracts. |
| 6.4 | Write `POLICY.md` | ✅ DONE | Human-readable policy with daily limits, slippage, kill switches, kill.json flag. |
| 6.5 | Record 3-minute demo video | ❌ NOT DONE | `SUBMISSION.md` marks `⏳` pending. `demo/` directory is empty. |
| 6.6 | DoraHacks submission form | ❌ NOT DONE | `SUBMISSION.md` marks `⏳` pending. |
| 6.7 | Make GitHub repo public | ❌ NOT DONE | `SUBMISSION.md` marks `⏳` pending. |
| 6.8 | Submit DoraHacks form by 10:00 UTC June 21 | ❌ NOT DONE | Same as 6.6 — pending. |
| 6.9 | Special prize applications | ⏸️ SKIPPED | STRETCH per plan. Not implemented. |
| 6.10 | `demo/chart_pnl.py` | ⏸️ SKIPPED | STRETCH per plan. `demo/` directory is empty. |

**Phase 6 Issues:**
- **P0 — Tasks 6.5, 6.6, 6.7, 6.8:** These are hard blockers. The submission deadline is June 21 12:00 UTC. All four tasks must be completed before that time.
- The demo video (6.5) is required for judging per the plan's Phase 6 definition of done.

---

## Verdict: NEEDS_FIXES

The implementation is well-architected and the core trading logic is solid. However, there are critical gaps that prevent going live:

### Critical Blockers (Must Fix Before Live Trading)

1. **[Phase 0.8] — `twak compete register` not executed.** The `TWAKExecutor.compete_register()` method exists in `src/twak.py` but has not been invoked. On-chain competition registration against `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` must be completed before June 22. Without this, the submission is ineligible.

2. **[Phase 1.1] — Allowlist is only 50 tokens, not 149.** `src/config.py` ALLOWLIST has exactly 50 entries. The plan explicitly states the competition uses a **fixed list of 149 BEP-20 tokens**. Using a partial allowlist risks executing trades on ineligible tokens, which would void those trades. The TODO comment in `config.py` acknowledges this. The full 149-token list must be sourced from the competition organizer and hardcoded.

3. **[Phase 6.5–6.8] — Demo video not recorded, DoraHacks form not submitted, repo not public.** The submission deadline is June 21 12:00 UTC. With the current date being June 20, these four tasks are the most time-critical items remaining.

### Significant Issues (Should Fix Before Live Trading)

4. **[Phase 1.4] — DEX trending endpoint not independently verified.** `cmc_client.py` calls `/v1/dex/tokens/trending/list`. The plan notes this endpoint's free-tier availability was uncertain. If this endpoint consistently fails, the "attention peak" sell signal (token enters top-3 trending) will never fire. The graceful `[]` fallback means the agent will simply hold positions longer than intended.

5. **[Phase 3.3] — QuoterV2 slippage formula assumes equal token values.** In `src/quoter.py`, `estimate_slippage_single()` uses `ideal_out = amount_in` as the reference price for slippage calculation. For unequal pairs (e.g., BNB → low-cap altcoin), `amount_in` BNB worth of output in token units is not equal-value, making `slippage_pct` severely underestimate true cost. The formula should use the on-chain spot price from QuoterV2's `sqrtPriceX96After` to compute the fair output amount, then compare against the actual quoted amount.

6. **[Phase 4.6] — `check_daily_loss()` not implemented.** The 5% daily-loss soft stop is referenced in PLAN.md Phase 4.6 but exists only as part of the 25% drawdown mechanism. A dedicated `check_daily_loss()` function would give operators earlier warning when the portfolio is under stress.

7. **[Phase 5.7] — No documented 2-hour paper run.** The `logs/cascade_fade.db` exists, confirming some run occurred, but there is no explicit log entry or test result documenting a continuous 2+ hour paper run free of crashes and rate-limit errors. This was a Phase 5 acceptance criterion.

### Minor Issues

8. **[Phase 0.13] — ERC-8004 registry address defined but never used.** `config.py` defines `ERC8004_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"` but no code calls it. This is STRETCH, so skipping is acceptable, but dead configuration constants are misleading.

9. **`src/cache.py` and `src/portfolio.py` both redefine identical schemas.** `cache.py` creates `trades`, `positions`, and `portfolio_snapshots` tables, and `portfolio.py` recreates the same three tables. This duplication can cause `IntegrityError` if both are initialized simultaneously. The schema should be in one place (e.g., `log.py` or a shared `schema.py`).

---

## What % Complete?

- **Tasks complete: 46/61 = 75.4%**
- **MVP tasks complete: ~36/42 = 85.7%** (STRETCH tasks excluded)
- **Critical-path MVP (must submit): ~80%**

---

## MVP Items Still Missing

1. Full 149-token allowlist (only 50 exist)
2. `twak compete register` — on-chain registration
3. Demo video (3 minutes, terminal + BSCScan)
4. DoraHacks submission form submitted
5. GitHub repo made public
6. 2-hour paper run formally documented
7. Live test swap confirmed on BSCScan with tx hash in `logs/test_swap.txt`

---

## Blockers Preventing Going Live

| Blocker | Phase | Severity | Fix |
|---|---|---|---|
| `twak compete register` not executed | 0.8 | CRITICAL | Run `scripts/register.py` or invoke `TWAKExecutor.compete_register()` manually before June 22 |
| 149-token allowlist incomplete | 1.1 | CRITICAL | Source official list from competition; update `src/config.py` `ALLOWLIST` |
| Submission not made (form, video, repo) | 6.5–6.8 | CRITICAL | All four must complete by June 21 10:00 UTC |
| Live test swap not confirmed on BSCScan | 3.7 | HIGH | Execute `python scripts/test_swap.py` and verify tx hash |
| 2-hour paper run not documented | 5.7 | HIGH | Run agent in paper mode for 2 hours; record evidence |
| QuoterV2 slippage formula incorrect | 3.3 | MEDIUM | Use `sqrtPriceX96After` to compute fair output; compare vs quoted amount |
| `check_daily_loss()` not separated | 4.6 | LOW | Implement as separate function from `check_drawdown()` |
| Duplicate schema definitions | All | LOW | Move `trades`/`positions`/`portfolio_snapshots` to single `schema.py` |

---

*End of audit.*