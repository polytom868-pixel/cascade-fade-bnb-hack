#!/usr/bin/env python3
"""Execute one live test swap on BSC mainnet."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import ALLOWLIST
from src.quoter import Quoter
from src.twak import TWAKExecutor
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def main() -> None:
    twak = TWAKExecutor()
    quoter = Quoter()

    # Show wallet address
    addr = await twak.get_address()
    print(f"Wallet address: {addr or 'unknown'}")

    # Check balance
    bal = await twak.get_balance()
    print(f"Balance: {bal}")

    # Quote a tiny swap: $5 USDT → BNB
    from_sym, to_sym = "USDT", "BNB"
    amount = 5.0
    q = quoter.estimate_slippage_single(
        from_sym, to_sym, amount,
        from_addr=ALLOWLIST.get(from_sym), to_addr=ALLOWLIST.get(to_sym),
    )
    print(f"Quote {amount} {from_sym} → {to_sym}: {q}")

    if q.get("status") != "ok":
        print("Quote failed — aborting swap test.")
        return

    if q.get("slippage_pct", 1.0) > 0.01:
        print(f"Slippage too high ({q['slippage_pct']:.2%}) — aborting.")
        return

    print("\nExecuting swap...")
    result = await twak.swap(amount, from_sym, to_sym, slippage=0.5, quote_only=False)
    print(f"Result: {result}")

    if result.get("tx_hash"):
        print(f"\n✅ Swap executed! Tx: {result['tx_hash']}")
        print(f"View on BSCScan: https://bscscan.com/tx/{result['tx_hash']}")
        # Save to file
        log_path = Path(__file__).parent.parent / "logs" / "test_swap.txt"
        log_path.write_text(f"{from_sym} {amount} → {to_sym} | tx={result['tx_hash']}")
    else:
        print("\n❌ Swap failed.")


if __name__ == "__main__":
    asyncio.run(main())
