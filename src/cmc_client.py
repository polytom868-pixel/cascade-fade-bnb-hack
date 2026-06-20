"""Async CoinMarketCap REST client with bulk fetch, retries, and caching."""
import asyncio
import logging
import os
from typing import Any

import aiohttp

from src.config import (
    CMC_BASE_URL,
    CMC_DEX_TRENDING,
    CMC_FEAR_GREED,
    CMC_QUOTES_LATEST,
    CMC_RETRIES,
    CMC_RETRY_BACKOFF,
    CMC_TIMEOUT,
)
from src.utils import retry_async

logger = logging.getLogger("cascadefade.cmc")


class CMCClient:
    """Async CMC REST client."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("CMC_API_KEY", "")
        if not self.api_key:
            logger.warning("CMC_API_KEY not set — CMC calls will fail")
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(5)  # limit concurrent requests

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                    "X-CMC_PRO_API_KEY": self.api_key,
                },
                timeout=aiohttp.ClientTimeout(total=CMC_TIMEOUT),
            )
        return self._session

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Make a rate-limited, retry-backed request."""
        async with self._semaphore:
            session = await self._get_session()
            url = f"{CMC_BASE_URL}{path}"

            async def _do() -> dict[str, Any]:
                async with session.request(method, url, **kwargs) as resp:
                    data = await resp.json()
                    if resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 60))
                        logger.warning("CMC rate limited, retry after %ds", retry_after)
                        raise asyncio.TimeoutError(f"Rate limited, retry after {retry_after}s")
                    if resp.status != 200:
                        raise RuntimeError(f"CMC {resp.status}: {data.get('status', {}).get('error_message', 'unknown error')}")
                    return data

            return await retry_async(
                _do,
                retries=CMC_RETRIES,
                backoff=CMC_RETRY_BACKOFF,
                exceptions=(aiohttp.ClientError, asyncio.TimeoutError, RuntimeError),
            )

    async def get_bulk_quotes(self, symbol_map: dict[str, str]) -> dict[str, dict[str, Any]]:
        """Fetch latest quotes for all symbols in one bulk call.

        symbol_map: {symbol: cmc_id} (cmc_id may be empty string; falls back to symbol).
        Returns: {symbol: quote_dict}.
        """
        if not symbol_map:
            return {}

        # Prefer numeric IDs; fallback to symbols
        ids = []
        symbols = []
        for sym, cid in symbol_map.items():
            if cid and cid.isdigit():
                ids.append(cid)
            else:
                symbols.append(sym)

        params: dict[str, str] = {}
        if ids:
            params["id"] = ",".join(ids)
        if symbols:
            params["symbol"] = ",".join(symbols)

        data = await self._request("GET", CMC_QUOTES_LATEST, params=params)
        result: dict[str, dict[str, Any]] = {}
        for sym in symbol_map:
            result[sym] = self._extract_quote(data, sym)
        return result

    def _extract_quote(self, data: dict[str, Any], symbol: str) -> dict[str, Any]:
        status = data.get("status", {})
        if status.get("error_code"):
            return {"error": status.get("error_message", "unknown")}

        raw = data.get("data", {})
        # CMC may return a dict keyed by symbol, where values can be dict or list
        entry = raw.get(symbol)
        if isinstance(entry, list):
            # Select the primary token (usually top-ranked, cmc_rank smallest integer)
            entry = min(entry, key=lambda e: e.get("cmc_rank") or 999_999)
        if not isinstance(entry, dict):
            return {"error": f"Symbol {symbol} not found in response"}

        usd = entry.get("quote", {}).get("USD", {})
        return {
            "price": usd.get("price", 0.0),
            "volume_24h": usd.get("volume_24h", 0.0),
            "percent_change_1h": usd.get("percent_change_1h", 0.0),
            "percent_change_24h": usd.get("percent_change_24h", 0.0),
            "percent_change_7d": usd.get("percent_change_7d", 0.0),
            "market_cap": usd.get("market_cap", 0.0),
            "last_updated": usd.get("last_updated", ""),
            "name": entry.get("name", ""),
            "cmc_rank": entry.get("cmc_rank", None),
        }

    async def get_fear_greed(self) -> dict[str, Any] | None:
        """Fetch latest Fear & Greed index."""
        try:
            data = await self._request("GET", CMC_FEAR_GREED)
            d = data.get("data", [{}])[0]
            return {
                "value": d.get("value", 50),
                "classification": d.get("value_classification", "Neutral"),
            }
        except Exception as exc:
            logger.warning("Fear & Greed fetch failed: %s", exc)
            return None

    async def get_dex_trending(self) -> list[str]:
        """Fetch top trending DEX tokens. Returns list of symbols.

        May return empty list if endpoint unavailable or rate-limited.
        """
        try:
            data = await self._request("GET", CMC_DEX_TRENDING)
            tokens = data.get("data", {}).get("tokens", [])
            return [t.get("symbol", "").upper() for t in tokens if t.get("symbol")]
        except Exception as exc:
            logger.warning("DEX trending fetch failed: %s", exc)
            return []

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
