"""Async CoinMarketCap REST client with bulk fetch, retries, and caching."""
import asyncio
import atexit
import logging
import os
import time
import warnings
from typing import Any

import aiohttp

from src.config import CACHE_TTL_SECONDS

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

# Module-level resolver and connector shared across all CMCClient instances.
# DNS resolution is 400-800ms; pre-resolving avoids that cost on every request.
_resolver: aiohttp.AsyncResolver | None = None
_connector: aiohttp.TCPConnector | None = None


def _build_connector() -> aiohttp.TCPConnector:
    global _resolver, _connector
    if _connector is None:
        _resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8"])
        _connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            enable_cleanup_closed=True,
            force_close=False,
            resolver=_resolver,
        )
    return _connector


class CMCClient:
    """Async CMC REST client."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("CMC_API_KEY", "")
        if not self.api_key:
            logger.warning("CMC_API_KEY not set - CMC calls will fail")
        self._headers = {
            "Accept": "application/json",
            "X-CMC_PRO_API_KEY": self.api_key,
            "Accept-Encoding": "gzip",
            "Connection": "keep-alive",
        }
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(5)  # limit concurrent requests
        self._last_success: float = 0.0
        self._cached_result: dict[str, dict[str, Any]] = {}
        atexit.register(self._sync_close)

    def _get_session(self) -> aiohttp.ClientSession:
        """Return the persistent session, creating it once if necessary."""
        if self._session is None or self._session.closed:
            connector = _build_connector()
            timeout = aiohttp.ClientTimeout(total=CMC_TIMEOUT, connect=10)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=self._headers,
                auto_decompress=True,
            )
        return self._session

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Async entry point to get or create the session (loop-aware)."""
        return self._get_session()

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Make a rate-limited, retry-backed request."""
        async with self._semaphore:
            session = self._get_session()
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
        Returns: {symbol: quote_dict}.  On failure returns stale cached data if
        within CACHE_TTL_SECONDS of the last successful fetch.
        """
        if not symbol_map:
            return {}

        # Prefer numeric IDs; fallback to symbols — pre-join once per call
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

        # Always reuse the persistent session — never recreate here
        session = self._get_session()
        url = f"{CMC_BASE_URL}{CMC_QUOTES_LATEST}"

        # Retry logic with exponential backoff
        last_error: Exception | None = None
        for attempt in range(CMC_RETRIES):
            try:
                async with session.get(url, params=params, headers=self._headers) as resp:
                    data = await resp.json()
                    if resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 60))
                        logger.warning("CMC rate limited, retry after %ds", retry_after)
                        raise asyncio.TimeoutError(f"Rate limited, retry after {retry_after}s")
                    if resp.status != 200:
                        raise RuntimeError(f"CMC {resp.status}: {data.get('status', {}).get('error_message', 'unknown error')}")
                    result: dict[str, dict[str, Any]] = {}
                    for sym in symbol_map:
                        result[sym] = self._extract_quote(data, sym)
                    self._cached_result = result
                    self._last_success = time.monotonic()
                    return result
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
                last_error = e
                if attempt < CMC_RETRIES - 1:
                    await asyncio.sleep(CMC_RETRY_BACKOFF * (2 ** attempt))
                    # Session stays alive across retries — only recreate if actually closed
                    if self._session is None or self._session.closed:
                        self._session = aiohttp.ClientSession(
                            connector=_build_connector(),
                            timeout=aiohttp.ClientTimeout(total=CMC_TIMEOUT, connect=10),
                            headers=self._headers,
                            auto_decompress=True,
                        )
                else:
                    logger.error("CMC fetch failed after %d attempts: %s", CMC_RETRIES, e)

        # Fallback to cached data if available
        if self._cached_result and (time.monotonic() - self._last_success) < CACHE_TTL_SECONDS:
            logger.warning("CMC fetch failed, returning stale cached data")
            return self._cached_result
        if last_error:
            raise last_error
        raise RuntimeError("CMC fetch failed with unknown error")

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

    def __del__(self) -> None:
        """Warn if session was not explicitly closed."""
        if self._session and not self._session.closed:
            warnings.warn(
                "CMCClient session not closed! Call await client.close() explicitly.",
                ResourceWarning,
            )

    def _sync_close(self) -> None:
        """Synchronous cleanup for atexit - only closes if loop is not running."""
        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop - safe to close synchronously
                asyncio.run(self.close())
            # else: loop is running; close() must be called explicitly