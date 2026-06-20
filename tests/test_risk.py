#!/usr/bin/env python3
"""Unit tests for risk management layer."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import (
    HEARTBEAT_SIZE_USD,
    MAX_DRAWDOWN_PCT,
    MAX_POSITION_PCT,
    MAX_POSITIONS,
    PORTFOLIO_FLOOR_USD,
)
from src.portfolio import Portfolio
from src.risk import RiskGuard


@pytest.mark.asyncio
async def test_drawdown_kill() -> None:
    """Hard stop triggers at 25% drawdown."""
    portfolio = Portfolio()
    risk = RiskGuard(portfolio)
    try:
        result = await risk.check_drawdown({"drawdown_pct": 0.24})
        assert result["safe"] is True, "24% drawdown should be safe"
        assert result["action"] == "continue"

        result = await risk.check_drawdown({"drawdown_pct": 0.25})
        assert result["safe"] is False, "25% drawdown should trigger kill"
        assert result["action"] == "kill_all"

        result = await risk.check_drawdown({"drawdown_pct": 0.30})
        assert result["safe"] is False
    finally:
        await portfolio.close()


@pytest.mark.asyncio
async def test_portfolio_floor() -> None:
    """Stop new trades if portfolio < $5."""
    portfolio = Portfolio()
    risk = RiskGuard(portfolio)
    try:
        result = await risk.check_portfolio_floor({"total": 5.0})
        assert result["safe"] is True

        result = await risk.check_portfolio_floor({"total": 4.99})
        assert result["safe"] is False
        assert result["action"] == "stop_new_trades"
    finally:
        await portfolio.close()


@pytest.mark.asyncio
async def test_position_size() -> None:
    """Position size respects portfolio % and cash limits."""
    portfolio = Portfolio()
    risk = RiskGuard(portfolio)
    try:
        size = risk.position_size(cash=1000, portfolio_value=1000)
        assert size == 100.0, f"Expected 100, got {size}"

        size = risk.position_size(cash=50, portfolio_value=1000)
        assert size == 50.0, f"Expected 50, got {size}"

        size = risk.position_size(cash=3, portfolio_value=1000)
        assert size == 3.0, f"Expected cash-limited 3, got {size}"

        size = risk.position_size(cash=1000, portfolio_value=50)
        assert size == 5.0, f"Expected floor 5 for tiny portfolio, got {size}"
    finally:
        await portfolio.close()


@pytest.mark.asyncio
async def test_pre_trade_checks() -> None:
    """Pre-trade gate rejects bad conditions."""
    portfolio = Portfolio()
    risk = RiskGuard(portfolio)
    try:
        result = risk.pre_trade_check(
            {"total": 100, "drawdown_pct": 0.1}, 0.005, 0
        )
        assert result["approved"] is True

        result = risk.pre_trade_check(
            {"total": 100, "drawdown_pct": 0.25}, 0.005, 0
        )
        assert result["approved"] is False

        result = risk.pre_trade_check(
            {"total": 4, "drawdown_pct": 0.05}, 0.005, 0
        )
        assert result["approved"] is False

        result = risk.pre_trade_check(
            {"total": 100, "drawdown_pct": 0.05}, 0.005, 2
        )
        assert result["approved"] is False

        result = risk.pre_trade_check(
            {"total": 100, "drawdown_pct": 0.05}, 0.02, 0
        )
        assert result["approved"] is False
    finally:
        await portfolio.close()


@pytest.mark.asyncio
async def test_heartbeat() -> None:
    """Heartbeat triggers when no trade in 22h+."""
    portfolio = Portfolio()
    risk = RiskGuard(portfolio)
    try:
        result = await risk.check_heartbeat()
        assert result["needed"] is True

        pair = risk.select_heartbeat_pair([])
        assert pair is not None
        assert pair[0] in ("BNB", "USDT")

        pair = risk.select_heartbeat_pair(["BNB"])
        assert pair == ("BNB", "USDT")
    finally:
        await portfolio.close()