# Research Findings — Top 10 Blocking Questions Answered

## Date: 2026-06-20
## Method: Web search + official docs verification

---

## Q1: Where is the 149-token BEP-20 allowlist?

**Status:** ❌ NOT FULLY RESOLVED — but found clues

**Findings:**
- No official list is published on DoraHacks, CMC, or BNB Chain docs as of 2026-06-20.
- A GitHub commit from `asbestos22/narrative-rotation-index` (dated 2026-06-07) explicitly references a **"149-token whitelist"** aligned to BNB Hack Track 1 eligibility. This lists 48 tokens across 10 narratives.
- The DoraHacks page mentions "eligible tokens" but does not enumerate them.
- The competition contract `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` may have a view function for the allowlist, but no ABI is publicly documented.

**MITIGATION for build:**
- Start with the **top 50 BEP-20 tokens by market cap on BSC** (verified liquid pairs on PancakeSwap v3).
- Build the allowlist loader in `src/config.py` so it can be swapped out when the official list becomes available.
- Add a note in README: "Allowlist will be updated with the official 149-token list before the trading window opens."
- Query the competition contract on BSCScan for `getAllowlist()` or similar function once the ABI is sourced.

---

## Q2: CMC API rate limits exceed free tier (15K credits/month)

**Status:** ⚠️ MANAGEABLE with call reduction

**Findings:**
- **Basic (free) tier:** 15,000 credits/month, 50 req/min.
- The agent's naive plan (149 tokens × 48 polls/day) = ~217K requests/month. This EXCEEDS the free tier by 14×.
- **Keyless Public API** (`/trial-pro-api`): 35+ endpoints, no signup, rate-limited subset. Includes DEX spot-pairs and quotes but NOT trending tokens.
- **Credit system:** Credits are tied to data returned, not just request count. Bulk/batch calls count as 1 credit per call regardless of data volume.
- x402 endpoints cost 0.01 USDC per call (30/min per wallet).

**MITIGATION:**
- Use **`/v1/cryptocurrency/map`** (1 call) to get all 149 token IDs upfront.
- Use **`/v2/cryptocurrency/quotes/latest`** with `id` parameter comma-separated to bulk-fetch all 149 token prices in **ONE call** per poll. This reduces 149 calls to 1 call.
- Poll cadence: every 30 min = 48 calls/day for quotes + 48 calls/day for trending + 1 call/day for fear & greed = ~97 calls/day = ~2,910/month. Well under 15K.
- DEX trending can be polled less frequently (every 2 hours = 12/day = 360/month).
- Total: ~3,300 credits/month. Comfortable on free tier.

---

## Q3: CMC DEX trending endpoint availability on free tier

**Status:** ⚠️ PARTIALLY AVAILABLE — need verification

**Findings:**
- Endpoint: `POST /v1/dex/tokens/trending/list` — exists in CMC API docs.
- **Trial (keyless) API does NOT include trending tokens.** Trial covers 17 DEX endpoints but explicit trending is in the "authenticated" set.
- The Basic plan description says "35+ data endpoints" and "DEX API" included. Trending is listed under DEX API on the pricing page.
- CMC API docs show trending as part of the standard DEX API, not a premium-only endpoint.

**VERDICT:** Likely available on Basic tier, but if it returns 403/401, implement fallback:
- **Fallback sell signal:** Use price-based exit only (stop-loss 5%, take-profit 10%, 48h timeout). Trending is a bonus, not required.
- Cache trending data for 2 hours to reduce calls.

---

## Q4: TWAK swap output format

**Status:** ✅ RESOLVED

**Findings:**
- TWAK CLI supports `--json` flag for **machine-readable JSON output**.
- Command: `twak swap <amount> <from> <to> --chain bsc --slippage <pct> [--quote-only] --json`
- Default chain is `ethereum` — **must always pass `--chain bsc`**.
- `--quote-only` previews without executing.
- The quickstart docs show example output: `100 USDC → 0.0241 ETH via Jupiter`
- With `--json`, output is structured JSON (exact schema not fully documented but machine-parseable).

**BUILD IMPLICATION:**
- `src/twak.py` should always pass `--json --chain bsc --slippage 0.5`
- Parse JSON output for tx_hash, expected_output, status, error fields.
- Handle non-zero exit codes by checking stderr.

---

## Q5: TWAK compete register verification

**Status:** ⚠️ PARTIALLY RESOLVED

**Findings:**
- TWAK has a `compete` subcommand (confirmed in npm package: `compete.d.ts`).
- Trust Wallet blog explicitly says: "Register your agent on-chain before the live trading window opens on June 22: Trust Wallet Agent Kit compete register."
- Output format: Not documented in public CLI reference. Must test locally.
- DoraHacks requires "On-chain Proof" — the wallet address must be registered.

**MITIGATION:**
- Run `twak compete register --chain bsc --json` and capture output.
- Verify registration by checking BSCScan for a tx to `0x212c...aed5`.
- If `twak compete register` fails, check DoraHacks FAQ for manual registration instructions.

---

## Q6: SQLite + asyncio concurrency

**Status:** ✅ RESOLVED

**Findings:**
- Python `sqlite3` stdlib is **NOT async-safe**. Using it in asyncio causes blocking and potential corruption.
- Solution: Use **`aiosqlite`** library — wraps sqlite3 in a thread pool with async API.
- Best practices:
  - `PRAGMA journal_mode = WAL` — allows concurrent reads during writes.
  - `PRAGMA synchronous = NORMAL` — faster writes, acceptable durability.
  - `PRAGMA foreign_keys = ON` — enforce FK constraints.
  - Use `timeout=60` on connection to handle lock contention.
  - For write transactions, use `BEGIN IMMEDIATE` to acquire write lock early.

**BUILD IMPLICATION:**
- Add `aiosqlite` to `requirements.txt`.
- `src/log.py` uses `aiosqlite` with WAL mode.
- All DB operations are async (`await conn.execute(...)`).

---

## Q7: Pending tx / failure recovery

**Status:** ⚠️ NEEDS CUSTOM HANDLING

**Findings:**
- TWAK CLI does not document retry logic, idempotency keys, or pending-tx tracking.
- BSC block time is ~3 seconds. A swap should confirm within 1-2 blocks (3-6 seconds) but can take longer during congestion.
- TWAK may return a tx hash before confirmation (submitted to mempool but not mined).
- If the agent crashes or the subprocess dies mid-execution, the tx may be in-flight with no state in the agent's SQLite.

**MITIGATION:**
- After `twak swap` returns, poll BSCScan or the RPC for tx receipt using `web3.py` `w3.eth.get_transaction_receipt(tx_hash)`.
- Wait up to 60 seconds for confirmation. If not confirmed, mark as "pending" in SQLite.
- On agent restart, query SQLite for pending txs and re-verify their status before making new trades.
- Use a `nonce` tracker: query `w3.eth.get_transaction_count(wallet_address, 'pending')` before each swap.
- Prevent double-spending by checking pending txs before submitting new ones.

---

## Q8: Portfolio drawdown with stale prices

**Status:** ⚠️ NEEDS FALLBACK STRATEGY

**Findings:**
- CMC quotes/latest can be stale by minutes (not real-time).
- BSC has ~3s block times. A flash crash can happen faster than CMC updates.
- The agent needs the **best available price** for drawdown and slippage checks.

**MITIGATION:**
- **Primary price source:** CMC `/v2/cryptocurrency/quotes/latest` via bulk call (1 req for all 149 tokens).
- **Fallback price source:** Direct PancakeSwap QuoterV2 call for held positions. This gives on-chain spot prices without CMC delay.
- For drawdown: use the MORE CONSERVATIVE of CMC price and QuoterV2 price. If QuoterV2 shows a lower price, use that for drawdown calculation.
- Update prices every cycle (30 min). For held tokens, also do a QuoterV2 check every cycle.

---

## Q9: PancakeSwap QuoterV2 fee tier selection

**Status:** ✅ RESOLVED

**Findings:**
- PancakeSwap v3 fees: **0.01% (100), 0.05% (500), 0.25% (3000), 1% (10000)**.
- `quoteExactInputSingle` takes a struct with `tokenIn`, `tokenOut`, `fee`, `amountIn`, `sqrtPriceLimitX96`.
- For each token pair, the agent must try multiple fee tiers to find the best route.
- PancakeSwap Smart Router `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4` handles this automatically.

**MITIGATION:**
- For slippage estimation, try fee tiers in order: 500, 3000, 100, 10000.
- Use the tier with the highest `amountOut`.
- Alternatively, rely on TWAK's routing (which uses the Smart Router internally) and only use QuoterV2 as a sanity check.
- `src/quoter.py` tries all 4 fee tiers and picks the best.

---

## Q10: USDT pair availability for all 149 tokens

**Status:** ⚠️ NOT ALL TOKENS HAVE DIRECT USDT PAIRS

**Findings:**
- PancakeSwap v3 has deep liquidity for major pairs (BNB/USDT, CAKE/USDT, ETH/USDT).
- Smaller tokens may only have BNB pairs (token/BNB) or BUSD pairs.
- The agent's strategy specifies "USDT pairs preferred for heartbeat trade" but does not require all tokens to trade against USDT.
- TWAK's swap command supports any token pair that has liquidity.

**MITIGATION:**
- The agent should hold **BNB as the base trading currency** rather than USDT. BNB is the native gas token and has pairs with virtually every token on BSC.
- Strategy: Agent holds **USDT + BNB**. Buys tokens using BNB. Sells tokens back to BNB or USDT.
- Heartbeat trade: BNB ↔ CAKE or BNB ↔ USDT (both have deep v3 liquidity).
- `src/twak.py` should query TWAK for supported pairs before executing.
- If a token has no direct pair with BNB, skip it during signal evaluation.

---

## Additional Verified Facts

| Fact | Source | Implication |
|---|---|---|
| Submission deadline: **June 21, 12:00 UTC** | DoraHacks page | Build must complete by June 20 evening |
| `twak x402 pay --asset BNB` is documented | Trust Wallet blog | x402 MAY support BNB (contradicts architecture's "USDC on Base only") — needs testing |
| PancakeSwap MEV Guard RPC: `https://bscrpc.pancakeswap.finance` | Confirmed multi-source | Set as default RPC in `.env` |
| CMC `/v2/cryptocurrency/quotes/latest` supports bulk `id` parameter | CMC docs | Fetch all 149 prices in 1 call |
| SQLite WAL mode enables concurrent reads | SQLite docs | Safe for asyncio with `aiosqlite` |
| BSC block time ~3 seconds | BNB Chain docs | Tx confirmation expectation: 3-15 seconds |
| `twak serve` starts MCP server | Trust Wallet docs | Optional integration, not required for core loop |
| Developer-defined policy via TWAK: daily spend cap, allowlist | Trust Wallet blog | Document in `POLICY.md` and pass flags to every swap |
| No perp support in TWAK CLI | Verified from CLI ref | Agent is correctly spot-only |
| ERC-8183 is commerce/escrow | EIP-8183 | Correctly NOT used as PnL ledger |
| ERC-8004 agent identity on mainnet | EIP-8004 | Requires gas; testnet is gas-free via MegaFuel |
