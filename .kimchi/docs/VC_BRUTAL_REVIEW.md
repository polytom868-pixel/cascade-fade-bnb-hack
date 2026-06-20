# CASCADEFADE — BRUTAL VC REVIEW

**Reviewer:** Ruthless Capital (Managing Partner, Dream Destruction Division)  
**Check Size:** $36,000 (if I were insane enough to write it)  
**Verdict:** HARD PASS. Not even a "let's stay in touch." Blocked on Signal.

---

## 1. WOULD I TRUST THIS CODE WITH $1000 OF MY MONEY FOR 7 DAYS?

**Absolutely fucking not.**

Here's why: the codebase has **six confirmed blockers** and the "fixes" that were applied are band-aids on a fundamentally broken architecture. The project was built by someone who read a hackathon spec, copied addresses from Google, and called it a trading agent.

The allowlist — the single most important list of tradable assets — contains **50 tokens out of 149 required**, and roughly **20 of those addresses are completely fabricated**. Look at `src/config.py` lines 89-108. PYTH at `0xD3c0A2C8F3d0e9aF3C5D6B4F8A9E3c2D1B0A4F7e`? RAYDIUM at `0x14f5AB83D0bd40E75C8222255bc855a974568Dd5`? I made up more believable addresses in this sentence. These are placeholder hex strings. If the agent tries to route a live swap to one of these fake addresses, the transaction will revert and burn gas — if you're lucky. If you're unlucky, it routes to an actual contract that isn't what you think it is.

But forget the fake addresses. The **position tracking system was completely broken until a reviewer "fixed" it**. Buy trades were logged to SQLite but never recorded as open positions. This means stop-losses (5%) and take-profits (10%) physically could not fire because the agent had no memory of ever buying anything. The "fix" adds a call to `add_position()` — but the cash flow logic is still duct-taped together. `_execute_swap` now subtracts `amount * bnb_price` from cash in a branch that assumes `from_sym.upper() == "BNB"`, but the actual token amount_out is computed with a USD-equivalent formula that could return 0.0 if prices are missing. Every cycle, cash is recomputed from stale or partially-updated state.

The slippage estimator — the gatekeeper that decides whether a trade happens at all — was computing slippage as `(amount_in - amount_out) / amount_in` which only works when both tokens are worth ~$1. For a BNB→CAKE swap where BNB is $300 and CAKE is $2.50, this formula returns nonsense. It was "fixed" to use USD prices, but the fix requires passing a `price_map` through three layers of call stack, and if that map is missing a price, it silently falls back to the broken formula.

Oh, and the tests? They **pass as standalone scripts** but **FAIL under pytest** because someone typed `async def test_drawdown_kill(risk: RiskManager)` expecting pytest to magic a `risk` fixture into existence. It doesn't. The tests are decorative.

**In short:** This agent would either (a) do nothing, (b) burn gas on reverts to fake addresses, or (c) lose track of its own positions and trade itself into a drawdown it can't measure correctly. My $1000 would be evaporated by incompetence, not market conditions.

---

## 2. WHAT IS THE SINGLE BIGGEST REASON THIS WILL LOSE MONEY DURING THE TRADING WINDOW?

**The agent cannot correctly compute its own portfolio value, which means it cannot correctly size positions or enforce its own drawdown kill switch.**

This is the money shot. The entire risk layer is built on `portfolio.compute_value(quotes, cash)`, which takes a `cash_usd` parameter passed in from `decision.py`. That cash value is supposed to be updated after every trade, but it is derived through ad-hoc arithmetic in `_execute_swap`:

```python
if from_sym.upper() == "BNB":
    bnb_price = price_map.get("BNB", {}).get("price", 0.0) or 300.0  # HARDCODED FALLBACK
    cash_after = cash - (amount * bnb_price)
else:
    bnb_price = price_map.get("BNB", {}).get("price", 0.0) or 300.0
    cash_after = cash + (amount_out * bnb_price)
```

This is wrong in at least four ways:

1. **It assumes all buys use BNB as the source token.** If the heartbeat buys BNB with USDT, `from_sym` is "USDT" and the `else` branch adds `amount_out * bnb_price` to cash — but `amount_out` was computed as a USD-equivalent amount, not actual received BNB tokens. So cash gets credited with a fantasy number.

2. **When selling a token for BNB, `amount_out` is computed as `amount * (p_in / p_out)`.** If `p_in` is the token's USD price and `p_out` is BNB's USD price, this gives a theoretical BNB amount. But the actual swap output comes from PancakeSwap QuoterV2, and slippage/gas means the real received amount differs. The agent credits its cash with a theoretical value that ignores slippage and fees.

3. **`compute_value` adds `cash_usd + positions_value`, but `positions_value` uses `quote.get("price", 0.0)`** multiplied by `pos["amount"]`. The `amount` stored in `add_position` is `result["amount_out"]` — which, again, is the theoretical computed amount, not the actual on-chain received tokens. The agent values its holdings with phantom numbers.

4. **The 25% drawdown hard stop triggers on `drawdown_pct` computed from peak portfolio value.** Since both peak and current value are wrong, the kill switch will fire either too late (after you've lost 40%) or prematurely (because a bad price made cash look lower than it is).

**The agent will hemorrhage money because it has no accurate picture of what it owns or what it's worth.** The strategy signal is irrelevant when the accounting is nonsense.

---

## 3. WHAT IS THE SINGLE BIGGEST REASON JUDGES WILL REJECT THIS SUBMISSION?

**The submission claims 149 tokens but delivers 50, with 20+ fabricated contract addresses, and not a single live swap has been confirmed on BSCScan.**

Judges review code. They read config files. When they open `src/config.py` and see a `TODO` comment saying "Replace with official 149-token list before trading window" followed by 50 entries where JUP, BONK, WIF, FLOKI, PEPE, MEME, MAGA, AI, AGI, and OCEAN all share incrementing fake addresses like `0x15f6AC83D0bd40E75C8222255bc855a974568Dd6`, they will laugh and close the tab.

The SUBMISSION.md has checkboxes like:
- `[x] 149-token allowlist enforced (top 50 built; updating to 149)`
- `[ ] Wallet registered and funded before June 22`
- `[ ] Live test swap confirmed on BSCScan`
- `[ ] 2+ hour paper run completed`

Three of those are unchecked. The checked one is a lie.

The `scripts/test_swap.py` file exists but the audit notes there is no saved tx hash in `logs/test_swap.txt`. This means nobody ever ran it successfully. The TWAK swap command syntax (`twak swap 5 USDT BNB --chain bsc --json --slippage 0.5`) was never verified against a real TWAK CLI installation. It might require contract addresses instead of symbols. It might require `--network` instead of `--chain`. It might require a different argument order. Nobody knows, because nobody tried.

No paper run. No live swap. Fake addresses. Unverified CLI syntax. This isn't a submission; it's a rough draft that needed another 48 hours.

---

## 4. IF THIS WERE MY STARTUP PITCH, WHAT WOULD I CHANGE TO NOT GET LAUGHED OUT OF THE ROOM?

**Stop pitching fiction. Build a demo that actually works.**

Right now the pitch is: "We have a sophisticated low-attention momentum fade strategy with MEV protection and hard risk guardrails." The reality is: "We have a Python script that calls a REST API, maintains a SQLite journal, and might send a subprocess to an unverified CLI if we ever test it."

Here's what I'd actually do:

**A. Fix the fundamentals before breathing the word 'alpha':**
- Get the real 149-token allowlist with verified BSC contract addresses. Not 50. Not 50 with fakes. All 149, and verify every address on BSCScan.
- Run `scripts/test_swap.py` with real money on BSC mainnet. Save the tx hash. Put it in the README.
- Run paper mode for 4+ hours, print the logs, and prove the agent cycles without crashing and without producing impossible portfolio values.

**B. Replace the broken accounting with something that tracks reality:**
- After every swap, query the *actual* wallet balance from BSC RPC or TWAK `wallet balance`. Do not compute theoretical cash from `amount * price`. Read the chain.
- Store `amount_out` from the actual QuoterV2 result, not `amount_in * (price_in / price_out)`.
- Single SQLite connection. Three connections to the same WAL-mode database is begging for `database is locked` errors under load.

**C. Make the tests real:**
- Write actual pytest fixtures. Run `pytest tests/`. Make it pass in CI.
- Add integration tests: mock CMC responses, run a paper cycle, verify portfolio state is coherent.
- Currently the "test suite" is five risk tests that check `if drawdown >= 0.25: kill`. This is not a test suite; it's a sanity check.

**D. Fix the signal to match the thesis:**
- The confidence score is `min(abs(change_7d) / 20.0, 1.0)`. A token up 50% in 7 days gets confidence 1.0. But your entire thesis is "buy BEFORE the crowd notices." A 50% weekly mover is the definition of crowd attention. Your ranking algorithm preferentially buys the exact hype you're pretending to avoid.

**E. Present evidence, not architecture diagrams:**
- Architecture.md is 10 sections of beautiful boxes and arrows. Nobody cares. Show a BSCScan tx. Show a 4-hour paper run log. Show the agent making a buy decision, executing a swap, and updating its journal with a real hash.

---

## 5. WHAT ASSUMPTIONS ARE SO NAIVE THEY MAKE YOU CRINGE?

**The top five naiveties, ranked by cringe intensity:**

### 5.1 "The QuoterV2 `amount_out` times CMC price approximates my portfolio value."
No. QuoterV2 simulates a route. It doesn't execute it. The actual output depends on block state, MEV, front-running, and liquidity depth. You're using a static quote as if it's a balance read. This is like valuing your checking account by asking the ATM how much it *would* dispense.

### 5.2 "If I hardcode addresses that look hex-y, the swaps will probably work."
`0x1CfD2084D0bd40E75C8222255bc855a974568DdD` for "AI" token. This is literally an incrementing sequence starting from `0x15f6...`. You didn't even generate random-looking fakes. You counted up. A middle-schooler faking a blockchain address would try harder.

### 5.3 "TWAK CLI accepts bare symbols like 'USDT' on BSC."
Maybe. Maybe it needs `0x55d398326f99059fF775485246999027B3197955`. Maybe it needs `USDT-BSC`. Maybe it only accepts symbols it has indexed. The ENTIRE execution layer depends on this assumption, and nobody tested it. You built a $36K trading strategy on a command-line flag you read in documentation once.

### 5.4 "Cache class-level variable is fine, and three separate SQLite connections to the same file is fine."
Sharing a class-level connection across instances means closing one cache closes all of them. Three WAL-mode writers means `database is locked` when the agent is under any real load. These are concurrency 101 mistakes. In a system that runs 24/7 executing trades, database deadlocks are not "edge cases"; they are inevitabilities.

### 5.5 "A 7-day positive price change with low DEX trending is alpha."
This is the core strategy, and it's cargo-cult quant. You have no backtest. No Sharpe ratio. No regime analysis. You're literally saying "if it went up last week and isn't trending today, buy it." This has a name: momentum chasing with a 7-day lag. You're not "buying the calm." You're buying whatever already moved after a week of data, when the real move is probably already over. And your confidence metric rewards the biggest lagged movers, so you'll buy the ripest retail bags.

---

## 3 IMMEDIATE TAKEAWAYS

### TAKEAWAY 1: YOUR ACCOUNTING LAYER IS BROKEN, AND IT WILL KILL YOU BEFORE THE MARKET DOES
Don't fix the signal. Don't add more tokens. Fix `Portfolio.compute_value` and `DecisionEngine._execute_swap` so they read *actual* on-chain balances instead of computing fantasy numbers from `price_in / price_out`. Until the agent knows what it actually owns, every other feature is theater.

### TAKEAWAY 2: YOU HAVE ZERO EXECUTION VERIFICATION
Run a single $5 live swap on BSC mainnet via TWAK. Just one. Save the tx hash. If it works, you know your command syntax, your RPC connection, and your wallet setup are valid. If it doesn't, you have 24 hours to fix it before the trading window opens. Right now you're flying blind into a $36K competition with an untested execution layer.

### TAKEAWAY 3: YOUR "STRATEGY" IS AN UNTESTED GUESS WITH INVERTED CONFIDENCE
Either backtest the "low-attention momentum fade" thesis on historical CMC + DEX data, or abandon the narrative and admit you're running a 7-day momentum scanner. If you keep the thesis, invert the confidence score to penalize extreme weekly moves (reward 5-15%, penalize >30%). And add an actual attention proxy — volume spike, social mentions, anything — because "not in top-3 DEX trending" is a binary filter, not a signal.

---

## FINAL WORD

This codebase has the bones of a decent hackathon project: asyncio architecture, SQLite journaling, CMC integration, TWAK wrapper, risk checks. The problem is none of the critical paths are verified. The allowlist is fake. The accounting is theoretical. The CLI syntax is untested. The tests are decorative. The strategy is a guess dressed in jargon.

**If I were judging this, I'd reject it.**  
**If I were investing, I'd zero the term sheet.**  
**If I were the founder, I'd spend the next 24 hours on execution verification, not feature additions.**

The good news: you can probably fix the fatal flaws in a focused day of work. The bad news: you're presenting this tomorrow, and right now it's a house of cards with a README.

-- Ruthless Capital  
*"We don't invest in potential. We invest in proof."*
