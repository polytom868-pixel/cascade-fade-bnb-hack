import logging
import statistics
from typing import Dict, List, Tuple, Any
from src.config import CASH_CURRENCY, HEARTBEAT_SIZE_USD, NARRATIVE_BASKETS
from src.cmc_client import CMCClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Regime Detection
# ---------------------------------------------------------------------------
REGIME_SIZING = {"RISK_ON": 1.0, "TRANSITION": 0.6, "RISK_OFF": 0.3}


def detect_market_regime(bnb_dominance: float, fear_greed: float, mcap_change_7d: float) -> Tuple[str, str]:
    if fear_greed > 65 and bnb_dominance < 50 and mcap_change_7d > 0.05:
        return "RISK_ON", "Altcoin-friendly: high greed, low BNB dominance, expanding mcap"
    elif fear_greed < 30 and bnb_dominance > 55:
        return "RISK_OFF", "Flight to safety: fear dominant, BNB absorbing capital"
    else:
        return "TRANSITION", "Mixed signals: regime unclear, reduced position sizing"


# ---------------------------------------------------------------------------
# 2. 5-Bucket Scoring (per narrative)
# ---------------------------------------------------------------------------
TOKEN_TO_NARRATIVE: dict[str, str] = {
    token: narrative
    for narrative, tokens in NARRATIVE_BASKETS.items()
    for token in tokens
}
BUCKET_WEIGHTS = {"momentum": 0.30, "liquidity": 0.25, "attention": 0.20, "fundamental": 0.15, "risk": 0.10}


def score_momentum(data: dict) -> Tuple[int, list]:
    score, reasons = 0, []
    rs = data.get("relative_strength_vs_bnb_7d", 1.0)
    if rs > 1.15: score += 35; reasons.append(f"Strong RS vs BNB ({rs:.3f}x)")
    elif rs > 1.05: score += 20; reasons.append(f"Moderate outperformance ({rs:.3f}x)")
    elif rs < 0.95: score -= 10; reasons.append(f"Underperforming BNB ({rs:.3f}x)")
    ret = data.get("basket_return_7d_pct", 0)
    if 0.05 < ret < 0.30: score += 25; reasons.append(f"Healthy 7d return ({ret*100:+.1f}%)")
    elif ret > 0.30: score += 10; reasons.append(f"Extended 7d return ({ret*100:+.1f}%)")
    elif ret < 0: score -= 10; reasons.append(f"Negative 7d return ({ret*100:+.1f}%)")
    dd = data.get("drawdown_from_30d_high_pct", 0)
    if 0.10 < dd < 0.25: score += 15; reasons.append(f"Pullback from 30d high ({dd*100:.0f}%)")
    rsi = data.get("rsi_14", 50)
    if rsi < 35: score += 20; reasons.append(f"RSI oversold ({rsi})")
    elif rsi > 70: score -= 15; reasons.append(f"RSI overbought ({rsi})")
    return max(0, min(100, score)), reasons


def score_liquidity(data: dict) -> Tuple[int, list]:
    score, reasons = 0, []
    vol = data.get("volume_change_7d_pct", 0)
    if vol > 0.30: score += 30; reasons.append(f"Volume expanding rapidly ({vol*100:.0f}% WoW)")
    elif vol > 0.10: score += 20; reasons.append(f"Healthy volume growth ({vol*100:.0f}% WoW)")
    elif vol < 0: score -= 15; reasons.append(f"Volume declining ({vol*100:.0f}% WoW)")
    liq = data.get("liquidity_usd", 0)
    if liq > 50_000_000: score += 20; reasons.append(f"Deep liquidity (${liq/1e6:.0f}M)")
    elif liq > 20_000_000: score += 10; reasons.append(f"Adequate liquidity (${liq/1e6:.0f}M)")
    spread = data.get("spread_pct", 0)
    if spread < 0.3: score += 15; reasons.append(f"Tight spread ({spread:.1f}%)")
    elif spread > 1.0: score -= 10; reasons.append(f"Wide spread ({spread:.1f}%)")
    return max(0, min(100, score)), reasons


def score_attention(data: dict) -> Tuple[int, list]:
    score, reasons = 0, []
    trending = data.get("trending_rank_avg", 50)
    if trending <= 10: score += 30; reasons.append(f"High CMC trending (avg #{trending})")
    elif trending <= 25: score += 20; reasons.append(f"Moderate trending (avg #{trending})")
    social = data.get("social_volume_24h", 0)
    if social > 10000: score += 25; reasons.append(f"High social velocity ({social:,}/24h)")
    elif social > 5000: score += 15; reasons.append(f"Moderate social activity ({social:,}/24h)")
    if data.get("kaito_mindshare_surge"): score += 15; reasons.append("Kaito mindshare surge")
    return max(0, min(100, score)), reasons


def score_fundamental(narrative: str, data: dict) -> Tuple[int, list]:
    score, reasons = 0, []
    if narrative in ("AI Tokens", "AI Agents"):
        if data.get("github_commits_7d", 0) > 200: score += 25; reasons.append(f"Active dev ({data['github_commits_7d']} commits/7d)")
        if data.get("developer_growth_30d_pct", 0) > 0.15: score += 20; reasons.append(f"Dev growth ({data['developer_growth_30d_pct']*100:.0f}%)")
        score += 15; reasons.append("AI structural tailwind")
    elif narrative == "RWA":
        if data.get("tvl_change_7d_pct", 0) > 0.08: score += 25; reasons.append(f"TVL expanding")
        if data.get("yield_premium_vs_treasuries_bps", 0) > 100: score += 15; reasons.append("Yield premium")
    elif narrative == "DePIN":
        if data.get("active_nodes_7d_growth_pct", 0) > 0.05: score += 25; reasons.append(f"Node growth")
        if data.get("network_utilization_pct", 0) > 0.5: score += 20; reasons.append(f"Utilization high")
    elif narrative == "Meme":
        if data.get("holder_growth_7d_pct", 0) > 0.1: score += 25; reasons.append(f"Holder growth")
        if data.get("whale_accumulation_7d_usd", 0) > 200_000: score += 15; reasons.append(f"Whale accumulation")
    elif narrative == "Privacy":
        if data.get("mixer_volume_7d_usd", 0) > 20_000_000: score += 25; reasons.append(f"Privacy demand")
        if data.get("shielded_pool_growth_7d_pct", 0) > 0.1: score += 15; reasons.append(f"Shielded pool growth")
    else:
        score += 10; reasons.append(f"{narrative} baseline utility")
    return max(0, min(100, score)), reasons


def compute_exhaustion_score(narrative: str, data: dict) -> Tuple[int, list]:
    penalty, reasons = 0, []
    if data.get("basket_return_7d_pct", 0) > 0.40 and data.get("volume_change_7d_pct", 0) < 0:
        penalty += 25; reasons.append("Parabolic return with declining volume — distribution likely")
    if data.get("social_volume_24h", 0) > 10000 and data.get("holder_growth_7d_pct", 0) < 0.03:
        penalty += 20; reasons.append("Social hype without holder growth")
    if data.get("drawdown_from_30d_high_pct", 999) < 0.05 and data.get("volume_change_7d_pct", 0) < 0:
        penalty += 20; reasons.append("Near 30d high with declining volume")
    if data.get("volatility_30d", 0) > 1.0:
        penalty += 15; reasons.append(f"Extreme volatility ({data['volatility_30d']*100:.0f}% ann.)")
    return min(penalty, 100), reasons


def score_risk_adjustment(narrative: str, data: dict) -> Tuple[int, list]:
    score, reasons = 100, []
    vol = data.get("volatility_30d", 0)
    if vol > 1.0: score -= 30; reasons.append(f"Extreme volatility")
    elif vol > 0.6: score -= 15; reasons.append(f"Elevated volatility")
    exhaustion, ex_reasons = compute_exhaustion_score(narrative, data)
    if exhaustion > 60: score -= 40; reasons.append(f"Exhaustion critical ({exhaustion}/100)")
    elif exhaustion > 30: score -= 20; reasons.append(f"Exhaustion caution ({exhaustion}/100)")
    return max(0, min(100, score)), reasons


# ---------------------------------------------------------------------------
# 3. Narrative Score Computation
# ---------------------------------------------------------------------------
REGIME_CONVICTION_CAP = {"RISK_ON": 100, "TRANSITION": 75, "RISK_OFF": 50}
CONVICTION_DECAY_RATE = 0.10


def compute_narrative_score(narrative: str, data: dict, regime: str, conviction_history: dict = None, day: int = 0) -> dict:
    m_score, m_reasons = score_momentum(data)
    l_score, l_reasons = score_liquidity(data)
    a_score, a_reasons = score_attention(data)
    f_score, f_reasons = score_fundamental(narrative, data)
    r_score, r_reasons = score_risk_adjustment(narrative, data)
    exhaustion_score = compute_exhaustion_score(narrative, data)[0]

    raw_score = (
        BUCKET_WEIGHTS["momentum"] * m_score +
        BUCKET_WEIGHTS["liquidity"] * l_score +
        BUCKET_WEIGHTS["attention"] * a_score +
        BUCKET_WEIGHTS["fundamental"] * f_score +
        BUCKET_WEIGHTS["risk"] * r_score
    )

    # Regime multiplier
    regime_mult = {"RISK_ON": 1.1, "TRANSITION": 0.9, "RISK_OFF": 0.7}.get(regime, 0.9)
    adjusted = int(raw_score * regime_mult)

    if regime == "RISK_OFF" and narrative == "Meme":
        adjusted = int(adjusted * 0.6)
    if regime == "RISK_ON" and narrative in ("AI Tokens", "DePIN"):
        adjusted = int(adjusted * 1.1)

    cap = REGIME_CONVICTION_CAP.get(regime, 75)
    adjusted = min(adjusted, cap)

    # Conviction decay
    if conviction_history is not None and narrative in conviction_history:
        days_stale = day - conviction_history[narrative].get("last_day", day)
        if days_stale > 1:
            adjusted = int(adjusted * ((1 - CONVICTION_DECAY_RATE) ** days_stale))
    if conviction_history is not None:
        conviction_history[narrative] = {"score": adjusted, "last_day": day}

    all_reasons = m_reasons + l_reasons + a_reasons + f_reasons + r_reasons
    verdict = "STRONG_LONG" if adjusted >= 60 else "LONG" if adjusted >= 20 else "NEUTRAL" if adjusted >= 10 else "AVOID"

    return {
        "narrative": narrative,
        "verdict": verdict,
        "conviction": adjusted,
        "cap": cap,
        "bucket_scores": {"momentum": m_score, "liquidity": l_score, "attention": a_score, "fundamental": f_score, "risk": r_score},
        "exhaustion_score": exhaustion_score,
        "reasons": all_reasons,
    }


def global_scan(regime: str, narrative_data: dict, conviction_history: dict = None, day: int = 0) -> dict:
    results = {}
    for narrative, data in narrative_data.items():
        results[narrative] = compute_narrative_score(narrative, data, regime, conviction_history, day)

    ranked = sorted(results.items(), key=lambda x: x[1]["conviction"], reverse=True)
    MIN_THRESHOLD = 20
    qualified = {n: max(d["conviction"], 1) for n, d in ranked if d["conviction"] >= MIN_THRESHOLD}
    sum_sq = sum(v ** 2 for v in qualified.values())
    weights = {n: round((qualified[n] ** 2 / sum_sq) * 100, 1) for n in qualified}
    weights.update({n: 0.0 for n, d in ranked if d["conviction"] < MIN_THRESHOLD})

    for n in weights:
        weights[n] = min(weights[n], 35.0)

    top = ranked[0]
    rotation = (f"CONCENTRATE_{top[0].upper().replace(' ', '_')}" if top[1]["conviction"] >= 60 else
                f"BALANCED with tilt toward {top[0]}" if top[1]["conviction"] >= 40 else
                "DEFENSIVE — increase stablecoin allocation")

    risks = []
    if regime != "RISK_ON": risks.append(f"Regime is {regime} — reduced allocation")
    if top[1]["exhaustion_score"] > 30: risks.append(f"{top[0]} exhaustion at {top[1]['exhaustion_score']}/100")

    return {
        "regime": regime,
        "conviction_cap": REGIME_CONVICTION_CAP.get(regime, 75),
        "narrative_rankings": ranked,
        "portfolio_weights": weights,
        "rotation_signal": rotation,
        "top_narrative": top[0],
        "top_verdict": top[1]["verdict"],
        "top_conviction": top[1]["conviction"],
        "risks": risks,
    }


# ---------------------------------------------------------------------------
# 4. Signal Engine Class
# ---------------------------------------------------------------------------
class SignalEngineClass:
    def __init__(self, cmc_client: CMCClient):
        self.cmc = cmc_client
        self.conviction_history: dict = {}
        self.day: int = 0

    async def _fetch_narrative_data(self) -> dict:
        # Only fetch basket tokens (30 unique across 10 narratives)
        from src.config import NARRATIVE_BASKETS, ALLOWLIST_TO_TOKEN_ADDRESS
        unique_tokens = set()
        for tokens in NARRATIVE_BASKETS.values():
            unique_tokens.update(tokens)
        symbol_map = {t: "" for t in unique_tokens if t in ALLOWLIST_TO_TOKEN_ADDRESS}
        try:
            qs = await self.cmc.get_bulk_quotes(symbol_map)
        except Exception as e:
            logger.warning("CMC fetch failed: %s", e)
            qs = {}
        # Group by narrative, average basket metrics
        data = {}
        for narrative, tokens in NARRATIVE_BASKETS.items():
            basket_data = [qs.get(t, {}) for t in tokens]
            avg_price = sum(b.get("price", 0) for b in basket_data) / max(len(basket_data), 1)
            volumes = [b.get("volume_24h", 0) for b in basket_data]
            max_vol = max(volumes) if volumes else 0
            vol_change = max_vol
            mcap_change = statistics.mean((b.get("percent_change_24h", 0) for b in basket_data)) if basket_data else 0
            data[narrative] = {
                "basket_return_7d_pct": mcap_change / 100 if mcap_change else 0,
                "volume_change_7d_pct": vol_change / max(avg_price, 1) * 100 if avg_price else 0,
                "relative_strength_vs_bnb_7d": 1.0,
                "drawdown_from_30d_high_pct": 0.15,
                "rsi_14": 50,
                "liquidity_usd": 10_000_000,
                "spread_pct": 0.5,
                "social_volume_24h": 0,
                "trending_rank_avg": 50,
                "volatility_30d": 0.5,
            }
        return data

    async def evaluate(self) -> dict:
        self.day += 1
        regime, reason = detect_market_regime(bnb_dominance=45, fear_greed=50, mcap_change_7d=0.02)
        narrative_data = await self._fetch_narrative_data()
        return global_scan(regime, narrative_data, self.conviction_history, self.day)