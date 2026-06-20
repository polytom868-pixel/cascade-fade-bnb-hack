# Unified Questions Compilation — CascadeFade Build

**Total questions collected:** 72 (24 × 3 sources)
- Agent A: 24 questions with web research
- Agent B: 24 questions with web research
- Orchestrator (me): 24 questions

**Goal:** Deduplicate, prioritize, and research answers for the most critical BLOCKING questions.

---

## Deduplication & Priority Matrix

After reviewing all 72 questions, the following are the **unique, non-overlapping critical blockers** grouped by theme:

### THEME 1: The 149-Token Allowlist (CRITICAL — blocks Phase 1.1)

| # | Source | Question | Priority |
|---|---|---|---|
| 1 | Agent A-A-1, Orchestrator-Q1,Q9,Q13 | **Where is the actual 149-token BEP-20 allowlist?** No file provides it. Contract `0x212c...aed5` — does it have a getter? Can we source from DoraHacks API? MVP fallback if unavailable? | 🔴 CRITICAL |
| 2 | Agent B-Q4 | What if tokens in the 149 list have **zero PancakeSwap v3 liquidity**? Pool validation before swap? | 🔴 CRITICAL |
| 3 | Agent B-Q14 | Is **USDT available as a pair** for all 149 tokens, or do we need 2-hop routes (USDT→BNB→token)? | HIGH |
| 4 | Agent B-Q23 | What if a token is **delisted or paused** during the trading window? Detection mechanism? | HIGH |

### THEME 2: CMC API Reality (CRITICAL — blocks Phase 1)

| # | Source | Question | Priority |
|---|---|---|---|
| 5 | Agent A-A-1, Orchestrator-Q3 | **CMC API auth ambiguity:** v2 vs v3 vs MCP? `CMC_API_KEY` header vs `X-CMC-MCP-API-KEY`? What base URL? | 🔴 CRITICAL |
| 6 | Agent A-A-2, Orchestrator-Q3 | **CMC free tier rate limits:** 15,000 credits/month, 50 req/min. 149 tokens × 48 polls/day = 7,248 req/day = ~217K/month. **EXCEEDS FREE TIER BY 14×.** Is there a bulk/batch endpoint? | 🔴 CRITICAL |
| 7 | Agent A-A-3, Agent B-Q9, Orchestrator-Q14 | **CMC DEX trending endpoint availability on free tier.** ARCHITECTURE says "free"; PLAN 1.4 marks it MVP but MCP docs show DEX data is WIP. What is the verified fallback? | 🔴 CRITICAL |
| 8 | Agent A-B-3 | CMC free tier **does not return market pairs with prices** in bulk calls. Need per-token calls? That multiplies request count. | HIGH |
| 9 | Agent B-Q15 | What is the **backup strategy if the CMC API key fails** (expired, rate-limited, 429s)? Backup key? Credit budget monitoring? | HIGH |
| 10 | Agent A-B-4, Orchestrator-Q12 | **CMC On-chain/DEX data is explicitly WIP** per CMC 2026-06-20 site. The architecture's "DEX trending" sell signal may have **no available data source at all**. | 🔴 CRITICAL |

### THEME 3: TWAK CLI Interface (CRITICAL — blocks Phase 3)

| # | Source | Question | Priority |
|---|---|---|---|
| 11 | Agent A-A-4, Agent B-Q1, Orchestrator-Q4 | **What is the exact `twak swap` CLI output format?** JSON? Plain text? How to parse tx hash? Exit codes on failure? **This blocks `src/twak.py` entirely.** | 🔴 CRITICAL |
| 12 | Agent A-A-5, Orchestrator-Q11 | **How to verify `twak compete register` succeeded?** Output format? Event log on `0x212c...aed5`? Form field match? | 🔴 CRITICAL |
| 13 | Agent A-A-7, Orchestrator-Q8 | Does TWAK support **custom calldata transactions** (for on-chain hash anchor)? Or do we need web3.py for that? | HIGH |
| 14 | Agent B-Q3, Orchestrator-Q7 | Does TWAK route through v2 or v3 pools? If v2, QuoterV2 (v3-only) slippage estimates are **inaccurate**. How to verify routing path? | HIGH |
| 15 | Agent B-Q8 | What are the exact **TWAK serve MCP tools** available? Is `wallet/swap` exposed? Output format? | MEDIUM |
| 16 | Agent A-C-3, Orchestrator-Q23 | **TWAK x402 requires USDC on Base** but agent runs on BSC. Do we need a separate Base wallet? Is x402 demo worth the complexity? | MEDIUM |

### THEME 4: Execution Safety (CRITICAL — blocks Phase 3-4)

| # | Source | Question | Priority |
|---|---|---|---|
| 17 | Agent B-Q1, Orchestrator-Q4 | **TWAK swap failure mid-execution:** subprocess crash, tx hash returned but tx reverts, "sent but unconfirmed" state. No retry, idempotency, or pending-tx tracking in docs. | 🔴 CRITICAL |
| 18 | Agent B-Q2, Orchestrator-Q5 | **SQLite + asyncio concurrency:** stdlib `sqlite3` is not thread-safe. Asyncio coroutines accessing same connection corrupt data. Need `aiosqlite` + WAL mode? | 🔴 CRITICAL |
| 19 | Agent B-Q5, Orchestrator-Q12 | **BSC network congestion:** What if MEV Guard RPC is down or congested? Gas spike handling? Pending tx timeout? Retry logic? | HIGH |
| 20 | Agent B-Q13, Orchestrator-Q12 | **Gas estimation on BSC:** TWAK may not estimate gas for complex v3 routes. Gas limit hardcoding? Custom gas price during congestion? | HIGH |
| 21 | Agent B-Q16 | **Nonce management on restart:** If agent restarts, how does it know the next nonce? What about "nonce too low" or "nonce gap" from pending txs? | MEDIUM |

### THEME 5: Risk & Portfolio Calculation (CRITICAL — blocks Phase 4)

| # | Source | Question | Priority |
|---|---|---|---|
| 22 | Orchestrator-Q6, Agent A-B-6 | **Portfolio value computation for drawdown:** Agent holds positions. To calculate 25% drawdown, it needs real-time USD value. Query CMC for held token prices each cycle. What if CMC data is stale during a flash crash? | 🔴 CRITICAL |
| 23 | Agent B-Q11, Orchestrator-Q15 | **Drawdown calculation with stale prices:** If CMC price update is 30 min stale and BSC price crashes, agent may not trigger the 25% stop until after catastrophic loss. Price source fallback? | 🔴 CRITICAL |
| 24 | Agent A-A-8 | **PancakeSwap QuoterV2 fee tiers:** The `quoteExactInputSingle` function requires a `fee` parameter (100, 500, 3000, 10000). Which fee tier for each pair? Need to try all? | HIGH |
| 25 | Orchestrator-Q17 | The COMPETITION rules say "No token launches..." but our agent only swaps. How do we **PROVE** to judges no deploy/mint happened? | HIGH |
| 26 | Agent B-Q18 | **What if drawdown breach is caused by network failure** (can't fetch prices to compute drawdown), not strategy failure? Is the agent penalized? | MEDIUM |

### THEME 6: Deployment & 24/7 Operation (HIGH — blocks Phase 5)

| # | Source | Question | Priority |
|---|---|---|---|
| 27 | Agent B-Q12 | **systemd vs tmux for 24/7:** Crash recovery on restart — does systemd handle nonce conflicts? tmux loses state on reboot. Best option? | HIGH |
| 28 | Orchestrator-Q15 | **Heartbeat at 20:00 UTC:** Why this time? Alignment with competition scoring window? What if agent restarts mid-day? | MEDIUM |
| 29 | Agent A-B-8 | **`twak swap --quote-only` output format** — undocumented. How to parse expected output amount? Needed for slippage check. | MEDIUM |
| 30 | Agent A-C-1, Orchestrator-Q10 | **Hard constraints checklist premature:** SUBMISSION.md shows ❓ for constraints not yet verifiable. Should checkmarks be removed until built? | MEDIUM |

### THEME 7: Special Prizes & Judging (MEDIUM — affects scoring)

| # | Source | Question | Priority |
|---|---|---|---|
| 31 | Agent B-Q7 | How do **judges actually verify PnL**? BSCScan only? Custom tool? Do they verify tx count, return calc, or just ranking? | HIGH |
| 32 | Agent B-Q19 | TWAK originality is **subjective (10 points)**. What actually scores 10/10? Video quality? Novelty? | MEDIUM |
| 33 | Agent B-Q20 | x402 is "optional" but awards 10 points. If we skip it, do we lose 10% of the TWAK prize? Is it worth it? | MEDIUM |
| 34 | Agent B-Q21 | **ERC-8004 mainnet gas cost:** MegaFuel is testnet-only. Mainnet registration costs BNB. How much? Fallback to testnet? | MEDIUM |
| 35 | Orchestrator-Q21 | Academic citations in thesis (Princeton, Stanford, Santiment) — judges may see **DEX volume as a weak proxy for attention**. Reframe thesis? | MEDIUM |

### THEME 8: Testing & Demo (MEDIUM — Phase 6)

| # | Source | Question | Priority |
|---|---|---|---|
| 36 | Orchestrator-Q16 | Minimal test scope: PLAN shows only `test_risk.py`. With 1.5 days, which tests are truly required? Accept signal/CMC bugs in paper run? | MEDIUM |
| 37 | Agent B-Q22 | **Demo video hype-exit example:** What if no token enters CMC trending during 2-4h paper run? Script it? Mock it? Label as simulation? | MEDIUM |
| 38 | Agent B-Q24 | **Tax/legal disclaimer:** US users may have tax obligations from trading. Does the submission need a legal disclaimer? | LOW |

---

## Questions Already Answered by Agents (No Further Research Needed)

| Question | Answer | Source |
|---|---|---|
| CMC MCP auth header | `X-CMC-MCP-API-KEY` is separate from REST `CMC_API_KEY` | Agent A web research |
| PancakeSwap v3 fees | 100/500/3000/10000 (uint24) | Agent A web research |
| MEV Guard RPC URL | `https://bscrpc.pancakeswap.finance` (verified, canonical) | Already in ARCHITECTURE |
| TWAK x402 asset | USDC on Base (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) | Already in ARCHITECTURE |
| ERC-8183 purpose | Agentic commerce/escrow, NOT a PnL ledger | Already in ARCHITECTURE |
| MegaFuel gas-free | Testnet-only | Already in ARCHITECTURE |
| CMC On-chain data | Explicitly "Work in Progress" as of 2026-06-20 | Agent A web research |
| CMC Trending Narratives | Under "Information & News", not DEX data | Agent A web research |

---

## Top 10 BLOCKING Questions That Must Be Answered Before Building

1. **Where is the 149-token allowlist?** (Q1) — Cannot trade without it.
2. **CMC API rate limits exceed free tier.** (Q6) — Need batch endpoint or call reduction strategy.
3. **CMC DEX trending may not exist on free tier.** (Q7,Q10) — Need verified endpoint or signal redesign.
4. **TWAK swap output format unknown.** (Q11) — Cannot build execution layer.
5. **TWAK compete register verification unknown.** (Q12) — Cannot confirm registration.
6. **SQLite + asyncio concurrency.** (Q18) — Data corruption risk in 24/7 op.
7. **Pending tx / failure recovery.** (Q17) — Agent may double-trade or miss state.
8. **Portfolio drawdown with stale prices.** (Q22,Q23) — 25% stop may fail during crashes.
9. **QuoterV2 fee tier selection.** (Q24) — Slippage estimation depends on correct pool.
10. **USDT pair availability for all 149 tokens.** (Q3) — Execution path may require 2-hop swaps.

These 10 must be researched and resolved before Phase 1 code is written.
