"""Narrative-basket decision engine: allocates across token baskets."""
import logging
import datetime
from typing import Dict, List, Tuple, Any
from src.config import (
    ALLOWLIST,
    NARRATIVE_BASKETS,
    MAX_POSITION_PCT,
    PORTFOLIO_FLOOR_USD,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TRADE_INTERVAL_MINUTES,
    HEARTBEAT_SIZE_USD,
)
from src.signal import REGIME_SIZING

CASH_CURRENCY = "USDT"
RISK_CURRENCY = "WBTC"
REBALANCE_THRESHOLD_PCT = 0.05
from src.risk import RiskGuard
from src.portfolio import Portfolio
from src.utils import fmt_bnb
from src.log import log_trade

logger = logging.getLogger(__name__)


def _size_position(cash: float, regime: str, conviction: int, cap: int) -> float:
    base = cash * MAX_POSITION_PCT
    sizing_mult = REGIME_SIZING.get(regime, 0.5)
    conviction_mult = min(conviction / max(cap, 1), 1.0)
    size = base * sizing_mult * conviction_mult
    size = max(size, HEARTBEAT_SIZE_USD)
    size = min(size, cash * MAX_POSITION_PCT)
    return round(size, 2)


def _split_across_basket(amount: float, basket: List[str]) -> List[Tuple[str, float]]:
    if not basket:
        return []
    per_token = amount / len(basket)
    return [(t, round(per_token, 2)) for t in basket if t in ALLOWLIST]


class DecisionEngine:
    def __init__(self, twak_client, portfolio: Portfolio, risk: RiskGuard):
        self.twak = twak_client
        self.portfolio = portfolio
        self.risk = risk
        self._last_buy_tick: Dict[str, float] = {}

    def _heartbeat_buy(self, token: str, amount: float):
        price = self.twak.price(f"{token}/{CASH_CURRENCY}")
        units = amount / max(price, 1e-9)
        self.risk.position_size(units, price, "heartbeat")
        self.portfolio.add(token, units, price)
        log_trade("BUY", token, units, price, amount)
        logger.info("Heartbeat buy %s $%.2f", token, amount)

    def evaluate(self, signal_result: dict, balances: dict) -> dict:
        actions = {"buys": [], "sells": [], "holds": [], "rejections": []}
        action_notes = []

        # --- risk guards ---
        dd_ok, dd_msg = self.risk.circuit_breaker(balances.get("usd_value", 0))
        action_notes.append(dd_msg)
        if not dd_ok:
            actions["rejections"].append(("ALL", dd_msg))
            return {"actions": actions, "notes": action_notes}

        floor_msg = self.risk.floor_guard(balances.get("total_value", 0))
        action_notes.append(floor_msg)

        expose_ok, expose_msg = self.risk.exposure_check(
            self.portfolio.total_exposure(), balances.get("total_value", 0)
        )
        action_notes.append(expose_msg)
        if not expose_ok:
            actions["rejections"].append(("ALL", expose_msg))
            return {"actions": actions, "notes": action_notes}

        # --- Extract top narrative ---
        top_narrative = signal_result.get("top_narrative", "")
        top_verdict = signal_result.get("top_verdict", "AVOID")
        top_conviction = signal_result.get("top_conviction", 0)
        regime = signal_result.get("regime", "TRANSITION")
        cap = signal_result.get("conviction_cap", 75)
        basket = NARRATIVE_BASKETS.get(top_narrative, [])

        logger.info(
            "Regime=%s Top=%s verdict=%s conviction=%d/%d basket=%s",
            regime, top_narrative, top_verdict, top_conviction, cap, basket,
        )

        cash = balances.get(CASH_CURRENCY, 0)

        # --- SELL logic: rebalance out of non-top narratives ---
        for position_token in self.portfolio.positions:
            # Find which narrative this token belongs to
            token_narrative = None
            for narr, tokens in NARRATIVE_BASKETS.items():
                if position_token in tokens:
                    token_narrative = narr
                    break
            if token_narrative == top_narrative and top_verdict in ("LONG", "STRONG_LONG"):
                actions["holds"].append(position_token)
                continue
            pos = self.portfolio.get(position_token)
            price = self.twak.price(f"{position_token}/{CASH_CURRENCY}")
            value = pos.units * price
            if value < PORTFOLIO_FLOOR_USD:
                actions["holds"].append(position_token)
                continue
            sell_ok, sell_msg = self.risk.pre_trade_check("SELL", value, balances.get("total_value", 0))
            if not sell_ok:
                actions["rejections"].append((position_token, sell_msg))
                continue
            self.portfolio.remove(position_token)
            log_trade("SELL", position_token, pos.units, price, value)
            actions["sells"].append({"token": position_token, "units": pos.units, "price": price, "value": value})
            logger.info("SELL %s $%.2f (%s)", position_token, value, sell_msg)

        # --- BUY logic: allocate to top narrative basket ---
        if top_verdict not in ("LONG", "STRONG_LONG") or not basket:
            action_notes.append(f"No buy: top narrative {top_narrative} verdict={top_verdict}")
            return {"actions": actions, "notes": action_notes}

        total_size = _size_position(cash, regime, top_conviction, cap)
        if total_size < HEARTBEAT_SIZE_USD:
            action_notes.append(f"Position size ${total_size:.2f} < heartbeat ${HEARTBEAT_SIZE_USD}")
            return {"actions": actions, "notes": action_notes}

        for token, amount in _split_across_basket(total_size, basket):
            now = datetime.datetime.now(datetime.timezone.utc).timestamp()
            last = self._last_buy_tick.get(token, 0)
            if now - last < TRADE_INTERVAL_MINUTES * 60:
                actions["rejections"].append((token, "cooldown"))
                continue
            price = self.twak.price(f"{token}/{CASH_CURRENCY}")
            units = amount / max(price, 1e-9)
            if amount < PORTFOLIO_FLOOR_USD:
                actions["rejections"].append((token, f"amt ${amount:.2f} < min ${MIN_TRADE_SIZE_USD}"))
                continue
            buy_ok, buy_msg = self.risk.pre_trade_check("BUY", amount, balances.get("total_value", 0))
            if not buy_ok:
                actions["rejections"].append((token, buy_msg))
                continue
            self.risk.position_size(units, price, "BUY")
            self.portfolio.add(token, units, price)
            self._last_buy_tick[token] = now
            log_trade("BUY", token, units, price, amount)
            actions["buys"].append({"token": token, "units": units, "price": price, "value": amount})
            logger.info("BUY %s $%.2f", token, amount)

        return {"actions": actions, "notes": action_notes}