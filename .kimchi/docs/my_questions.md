# My Questions (Orchestrator) — 24 Questions from the 3 MD Files

## ARCHITECTURE.md — 8 Questions

1. **CRITICAL: Where is the actual 149-token BEP-20 allowlist with contract addresses?**
   The ARCHITECTURE says it's "hardcoded" but no file or list is provided. Without the exact list with contract addresses, we cannot validate trades against the competition allowlist. Where can we source this list? Is it embedded in the competition contract ABI?

2. **CRITICAL: What is the exact SQLite schema for the trade journal?**
   ARCHITECTURE mentions fields (timestamp, signal, token_in, token_out, amount_in, amount_out, prices, slippage_estimate, tx_hash, signal_snapshot, realized_pnl, running_portfolio_value) but does not define SQL types, indexes, or foreign keys. What schema ensures fast lookups for drawdown calculations?

3. **HIGH: How does the CMC basic free tier (15,000 credits/month, 50 req/min) map to the agent's polling cadence?**
   If we poll 149 tokens every 30 minutes plus trending + fear & greed, that's ~151 requests per poll × 48 polls/day = 7,248 requests/day = ~217K/month, exceeding the free tier by 14×. Is there a bulk endpoint or do we need to poll fewer tokens?

4. **HIGH: What is the exact subprocess interface for `twak swap` — stdout format, exit codes, error messages?**
   ARCHITECTURE says "Python agent calls `twak` commands via subprocess" but doesn't document the output format (JSON? plain text?), exit codes on failure, or how to parse the tx hash from output. This is required to build `src/twak.py`.

5. **HIGH: What happens when a token in the 149 list has insufficient PancakeSwap v3 liquidity?**
   The strategy assumes all 149 tokens have sufficient liquidity for $5–$500 swaps. If a token only has v2 pools or thin liquidity, TWAK swap may fail or produce extreme slippage. How does the agent detect and skip illiquid tokens before attempting a swap?

6. **HIGH: How is portfolio value computed for drawdown calculations?**
   The agent holds 2 positions max. To calculate 25% drawdown, it needs real-time USD value of held tokens. Does it query CMC for current prices of held positions each cycle? What if CMC data is stale during a crash?

7. **MEDIUM: What is the QuoterV2 ABI and exact function signature for slippage estimation?**
   ARCHITECTURE references `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` but doesn't provide the ABI. `quoteExactInputSingle` takes (tokenIn, tokenOut, fee, amountIn, sqrtPriceLimitX96) — is that the function used? What fee tier (100, 500, 3000, 10000) should be used for each pair?

8. **MEDIUM: What is the exact mechanism for the on-chain hash anchor?**
   ARCHITECTURE says "self-transfer transaction (or via a tiny custom memo contract)" with keccak256 hash in the `data` field. This requires sending a BNB transaction with custom calldata — how is this done via TWAK? Does TWAK support `eth_sendTransaction` with custom data, or do we need web3.py for this?

---

## PLAN.md — 8 Questions

9. **CRITICAL: The PLAN says "Source from the competition organizer/contract in Phase 0; hardcode the best available list" for the 149-token allowlist. How do we actually query the contract for the list?**
   The competition contract is `0x212c61b9b72c95d95bf29cf032f5e5635629aed5` but no ABI or function name for getting the allowlist is documented. Is there a public getter? Or should we scrape DoraHacks/API for the list?

10. **CRITICAL: The demo video is listed as MVP but requires Phase 3 (live test swap) and Phase 5 (paper run) to be completed first. What is the critical path ordering if we're time-constrained?**
    If Phase 3 fails (can't execute a live swap), we can't film the demo video. What's the fallback for the demo — can we paper-trade and show the decision logic without a live tx hash?

11. **HIGH: Phase 0.6 says "Fund the wallet with 0.5+ BNB for gas and 500–1000 USDT." Where does this capital come from in the build environment?**
    We (the team) need to buy and transfer real BNB/USDT to the TWAK wallet. What exchange, bridge, or funding path is available? How much time does BSC transfer take? What if funding fails?

12. **HIGH: `twak compete register` is listed as CRITICAL MVP but the PLAN doesn't explain what arguments it takes or how to verify success.**
    What does `twak compete register` output? Does it require a competition ID, team ID, or just the wallet? How do we verify the registration on BSCScan — is there an event log or a `registered(wallet)` view function on the competition contract?

13. **HIGH: Phase 1.1 requires `src/config.py` with 149-token allowlist. If we can't source the full list by build time, what's the MVP fallback?**
    Can we start with a subset (e.g., top 20 BEP-20 tokens) and note in docs that it's a placeholder? Or does the competition require all 149 to be in the code at submission?

14. **HIGH: Phase 1.4 calls `get_dex_trending_tokens()` but the CMC basic free tier may not include DEX trending. What is the verified fallback?**
    The ARCHITECTURE says "DEX trending free; community trending Standard+" but PLAN 1.4 marks it as MVP. If the endpoint returns 403/401 on the free key, does the signal collapse? Should we implement a cached mock or skip the trending exit rule?

15. **MEDIUM: Phase 5.1 says "wake at 20:00 UTC daily for heartbeat trade." Why 20:00 UTC specifically?**
    Is this aligned with a BSC block time, CMC data refresh, or competition scoring window? What if the agent crashes and restarts — does it check "last trade time" from SQLite or just trust the schedule?

16. **MEDIUM: The file structure in §6 shows `tests/test_risk.py` but no `test_signal.py`, `test_cmc_client.py`, etc. Are other tests out of scope?**
    With only 1.5 days, which tests are truly required? If we only test risk (drawdown, floor, heartbeat), do we accept that signal and CMC client bugs might only surface during the paper run?

---

## SUBMISSION.md — 8 Questions

17. **CRITICAL: SUBMISSION.md lists "No token launches, liquidity openings, or airdrop pumping" as a rule, but our agent only swaps. How do we PROVE to judges that the agent does not deploy/mint/list?**
    Is this just a documentation claim, or do judges scan the wallet for contract creation txs? Should we add a guard in code that explicitly rejects any `create` / `deploy` operations?

18. **CRITICAL: SUBMISSION.md says wallet must be "registered via `twak compete register` before June 22" and "same address is also entered on the DoraHacks submission form." What if the registration tx fails or the form doesn't accept the address?**
    Is there a way to verify the form accepted the address? Can we query the competition contract to double-check registration succeeded?

19. **HIGH: The special prize scoring tables show "Maximum 100/100" and "Target Points" — are these official rubrics from DoraHacks or self-assigned estimates?**
    If judges use different criteria, our scoring alignment may be wrong. Where are the official judging rubrics published?

20. **HIGH: SUBMISSION.md shows a "Verified" checkmark (✅) next to "Portfolio value > $1 at each hour start" but no code exists yet. Is this premature?**
    Should we remove these checkmarks until verified in code? Or is the purpose of SUBMISSION.md to be aspirational?

21. **HIGH: The Evidence & Sources table cites academic papers (Princeton, Hebrew University, Stanford, Santiment). Are judges expected to read these? Should evidence be summarized inline?**
    If the strategy doesn't match the cited papers exactly, does this create a liability? The agent doesn't actually measure "social media attention" — it uses DEX activity as a proxy.

22. **MEDIUM: The demo video plan (§Demo Video Plan) assumes we can show a "hype-exit example" where a token enters CMC DEX trending and the agent sells. What if no token enters trending during our 2-4 hour paper run?**
    Do we script/mock this for the video, or wait for a real event? If scripted, how do we ensure it's clearly labeled as a simulation?

23. **MEDIUM: SUBMISSION.md claims "TWAK x402 uses USDC on Base" and that we might demonstrate it. But the agent runs on BSC. Do we need a separate Base wallet funded with USDC just for the x402 demo?**
    This adds complexity (two chains, two wallets, bridging USDC). Is the x402 demo worth the time, or should we drop it to focus on BSC trading?

24. **MEDIUM: The alpha thesis cites academic research on "limited-attention underreaction" but our signal doesn't actually measure attention directly. Is this a misalignment that could hurt judging?**
    We use DEX volume as a proxy for attention. If judges understand finance literature, they may see this as a weak proxy. Should we reframe the thesis or add a justification for the proxy?
