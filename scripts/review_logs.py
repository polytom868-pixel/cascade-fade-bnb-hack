#!/usr/bin/env python3
"""Review recent trades, PnL, and drawdown from SQLite log."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.log import TradeLogger
from src.portfolio import Portfolio


async def main() -> None:
    logger = TradeLogger()
    portfolio = Portfolio()

    print("=" * 60)
    print("RECENT TRADES")
    print("=" * 60)
    trades = await logger.get_recent_trades(limit=20)
    for t in trades:
        print(f"  [{t['ts']}] {t['side']:8s} {t['symbol']:10s} | amount={t['amount_in']:.4f} | "
              f"pnl={t['realized_pnl'] or 0:.2f} | mode={t['mode']} | status={t['status']} | tx={t['tx_hash'] or 'n/a'}")

    print("\n" + "=" * 60)
    print("PORTFOLIO SNAPSHOTS")
    print("=" * 60)
    # Use raw query for snapshots
    db = await portfolio._connect()
    async with db.execute(
        "SELECT ts, total_value, cash_value, positions_value, peak_value "
        "FROM portfolio_snapshots ORDER BY id DESC LIMIT 10"
    ) as cur:
        for row in await cur.fetchall():
            ts, total, cash, pos, peak = row
            dd = (peak - total) / peak * 100 if peak else 0
            print(f"  {ts} | total=${total:,.2f} | cash=${cash:,.2f} | pos=${pos:,.2f} | peak=${peak:,.2f} | dd={dd:.2f}%")

    await logger.close()
    await portfolio.close()


if __name__ == "__main__":
    asyncio.run(main())
