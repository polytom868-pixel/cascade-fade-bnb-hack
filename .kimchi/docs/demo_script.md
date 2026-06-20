# DEMO VIDEO SCRIPT (3 minutes)

## SCENE 1: Terminal Launch (0:00–0:15)
Command typed: `python -m src.agent --mode paper --cash 1000`
Narration: "CascadeFade launches in paper mode with $1,000 simulated capital."

## SCENE 2: Narrative Scan (0:15–0:45)
Show: Regime detected, Top narrative, 5-bucket scores
Narration: "Our narrative rotation engine scans ten baskets. In risk-on regimes, AI Agents scores highest."

## SCENE 3: Signal Confidence Output (0:45–1:15)
Show: verdict STRONG_LONG, conviction 78, exhaustion 22, position size 10%
Narration: "Structured confidence score with dynamic position sizing by regime and conviction."

## SCENE 4: TWAK Swap Execution (1:15–1:45)
Show: twak swap command + BSCScan tx hash
Narration: "Trust Wallet Agent Kit routes swaps directly on BNB Chain."

## SCENE 5: Risk Guardrail Demo (1:45–2:15)
Show: CIRCUIT BREAKER TRIPPED, sizing reduced to 10%, heartbeat buy
Narration: "25% drawdown triggers circuit breaker. Sizing drops. Heartbeat keeps us alive."

## SCENE 6: Portfolio Dashboard (2:15–2:45)
Show: PnL +$127, drawdown 8.3%, win rate 62%
Narration: "All trades journaled in SQLite. Every decision is auditable."

## SCENE 7: Closing + BSCScan (2:45–3:00)
Show: BSCScan wallet 0x3EE7...4D3d18
Narration: "CascadeFade: autonomous narrative rotation on BNB Chain. Real trades, real profits. Track 1, BNB Hack."

## RECORDING CHECKLIST
- [ ] Set terminal font 18pt
- [ ] Run `python -m src.agent --mode paper --cash 1000 --duration 180`
- [ ] Open BSCScan wallet tab
- [ ] Record 1080p 30fps
- [ ] Export MP4, upload unlisted