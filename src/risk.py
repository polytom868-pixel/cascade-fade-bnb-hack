"""Risk management: drawdown, portfolio floor, heartbeat, position sizing."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import (
    HEARTBEAT_HOUR_UTC,
    HEARTBEAT_SIZE_USD,
    MAX_DRAWDOWN_PCT,
    MAX_POSITION_PCT,
    MAX_POSITIONS,
    MAX_SLIPPAGE_PCT,
    PORTFOLIO_FLOOR_USD,
    STOP_LOSS_PCT,
    ALLOWLIST,
)
from src.portfolio import Portfolio

logger = logging.getLogger("cascadefade.risk")


class RiskGuard:
    """Enforce hard constraints and compute position sizes."""

    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio
        self.stop_loss_pct = STOP_LOSS_PCT

    async def check_drawdown(self, value: dict[str, Any]) -> dict[str, Any]:
        """Check if portfolio drawdown exceeds 25% hard stop.

        Returns: {"safe": bool, "action": str, "drawdown_pct": float}
        """
        dd = value.get("drawdown_pct", 0.0)
        safe = dd < MAX_DRAWDOWN_PCT
        action = "continue" if safe else "kill_all"
        if not safe:
            logger.critical("DRAWDOWN KILL: %.2f%% >= %.2f%%", dd * 100, MAX_DRAWDOWN_PCT * 100)
        return {"safe": safe, "action": action, "drawdown_pct": dd}

    async def check_portfolio_floor(self, value: dict[str, Any]) -> dict[str, Any]:
        """Check if portfolio is above $5 floor.

        Returns: {"safe": bool, "action": str}
        """
        total = value.get("total", 0.0)
        safe = total >= PORTFOLIO_FLOOR_USD
        action = "continue" if safe else "stop_new_trades"
        if not safe:
            logger.warning("FLOOR BREACH: %.2f < %.2f — stopping new entries", total, PORTFOLIO_FLOOR_USD)
        return {"safe": safe, "action": action}

    async def check_heartbeat(self) -> dict[str, Any]:
        """Check if daily heartbeat trade is needed.

        Trigger if no trade in last 22 hours, or if current UTC hour matches HEARTBEAT_HOUR.
        Returns: {"needed": bool, "reason": str}
        """
        last_ts = await self.portfolio.get_last_trade_ts()
        now = datetime.now(timezone.utc)

        if last_ts:
            try:
                last = datetime.fromisoformat(last_ts)
                hours_since = (now - last).total_seconds() / 3600
                if hours_since < 22:
                    return {"needed": False, "reason": f"last trade {hours_since:.1f}h ago"}
            except Exception:
                pass

        # Also enforce at heartbeat hour
        if now.hour == HEARTBEAT_HOUR_UTC:
            return {"needed": True, "reason": f"heartbeat hour {HEARTBEAT_HOUR_UTC}:00 UTC"}

        return {"needed": True, "reason": "no trade in 22h+"}

    # ---------------------------------------------------------------------------
    # Aliases for decision.py
    # ---------------------------------------------------------------------------

    async def circuit_breaker(self, portfolio_value: float) -> tuple[bool, str]:
        """Alias for check_drawdown — used by decision.py.

        Returns (ok, message) tuple matching what decision.py expects.
        Drawdown is inferred as (peak - current) / peak from DB.
        """
        db = await self.portfolio._connect()
        async with db.execute("SELECT MAX(peak_value) FROM portfolio_snapshots") as cur:
            row = await cur.fetchone()
        peak_value = row[0] if row and row[0] is not None else portfolio_value
        drawdown_pct = max(0.0, (peak_value - portfolio_value) / peak_value) if peak_value > 0 else 0.0
        result = await self.check_drawdown({"drawdown_pct": drawdown_pct})
        if result["safe"]:
            return True, "drawdown OK"
        return False, f"drawdown kill: {drawdown_pct:.2%} >= {MAX_DRAWDOWN_PCT:.2%}"

    async def floor_guard(self, total_value: float) -> str:
        """Alias for check_portfolio_floor — used by decision.py.

        Returns message string (empty if safe).
        """
        result = await self.check_portfolio_floor({"total": total_value})
        if result["safe"]:
            return ""
        return f"portfolio floor breach: ${total_value:.2f} < ${PORTFOLIO_FLOOR_USD}"

    def exposure_check(self, exposure: float, total_value: float) -> tuple[bool, str]:
        """Check if total exposure exceeds 90% of portfolio value.

        Returns (ok, message) tuple matching what decision.py expects.
        """
        if total_value <= 0:
            return True, ""
        exposure_ratio = exposure / total_value
        MAX_EXPOSURE_RATIO = 0.90
        if exposure_ratio > MAX_EXPOSURE_RATIO:
            return False, f"exposure {exposure_ratio:.2%} > {MAX_EXPOSURE_RATIO:.2%} of portfolio"
        return True, ""

    def position_size(self, cash: float, portfolio_value: float) -> float:
        """Compute max position size for a new trade.

        Rules:
        - Max 10% of portfolio value
        - Not more than available cash
        - Min $5 (heartbeat size) if cash allows
        Returns amount in USD.
        """
        max_by_pct = portfolio_value * MAX_POSITION_PCT
        size = min(max_by_pct, cash)
        # Only enforce heartbeat floor if portfolio is large enough to justify it
        min_portfolio_for_floor = HEARTBEAT_SIZE_USD * 5
        if cash >= HEARTBEAT_SIZE_USD and portfolio_value >= min_portfolio_for_floor:
            size = max(size, HEARTBEAT_SIZE_USD)
        return round(size, 2)

    def pre_trade_check(
        self,
        value: dict[str, Any],
        slippage_pct: float,
        held_count: int,
    ) -> dict[str, Any]:
        """Run all pre-trade risk checks.

        Returns: {"approved": bool, "reason": str}
        """
        # Drawdown
        dd = value.get("drawdown_pct", 0.0)
        if dd >= MAX_DRAWDOWN_PCT:
            return {"approved": False, "reason": f"drawdown {dd:.2%} >= {MAX_DRAWDOWN_PCT:.2%}"}

        # Floor
        total = value.get("total", 0.0)
        if total < PORTFOLIO_FLOOR_USD:
            return {"approved": False, "reason": f"portfolio ${total:.2f} < floor ${PORTFOLIO_FLOOR_USD}"}

        # Position count
        if held_count >= MAX_POSITIONS:
            return {"approved": False, "reason": f"max positions {MAX_POSITIONS} reached"}

        # Slippage
        if slippage_pct > MAX_SLIPPAGE_PCT:
            return {"approved": False, "reason": f"slippage {slippage_pct:.2%} > max {MAX_SLIPPAGE_PCT:.2%}"}

        return {"approved": True, "reason": "all checks passed"}

    def select_heartbeat_pair(self, held_symbols: list[str]) -> tuple[str, str] | None:
        """Select a safe heartbeat pair: BNB→USDT or USDT→BNB.

        Returns (from, to). Prefers not to sell held positions.
        """
        # Simple rotation: if we hold BNB, sell to USDT; else buy BNB with USDT
        has_bnb = "BNB" in [h.upper() for h in held_symbols] or "WBNB" in [h.upper() for h in held_symbols]
        if has_bnb:
            return ("BNB", "USDT")
        return ("USDT", "BNB")

    async def check_exits(
        self,
        positions: dict[str, dict[str, Any]],
        price_map: dict[str, dict[str, Any]],
        value: dict[str, Any],
    ) -> list[str]:
        """Check for positions that should be exited due to drawdown.

        First checks global portfolio drawdown, then checks per-position
        stop-loss based on entry price vs current price.

        Returns: list of token symbols to sell (no duplicates).
        """
        # Global drawdown check
        dd_result = await self.check_drawdown(value)
        if not dd_result["safe"]:
            logger.warning("Global drawdown kill triggered, exiting all positions")
            return list(positions.keys())

        # Per-position stop-loss check
        forced_sells: list[str] = []
        for token, pos in positions.items():
            entry = pos.get("entry_price", 0.0)
            current = price_map.get(token, {}).get("price") or 0.0
            if current > 0 and entry > 0:
                pct = (current - entry) / entry
                if pct <= -self.stop_loss_pct:
                    logger.warning(
                        "Position drawdown stop-loss: %s price=%.4f <= entry=%.4f (%.2f%%)",
                        token,
                        current,
                        entry,
                        pct * 100,
                    )
                    forced_sells.append(token)

        # Deduplicate
        return list(set(forced_sells))
