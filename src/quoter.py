"""PancakeSwap V3 QuoterV2 slippage estimator via web3.py."""
import asyncio
import logging
from typing import Any

from web3 import Web3

from src.config import (
    BSC_CHAIN_ID,
    BSC_RPC_URL,
    PCS_FEE_TIERS,
    PCS_V3_QUOTER_V2,
    WBNB,
)

logger = logging.getLogger("cascadefade.quoter")

# Minimal QuoterV2 ABI for quoteExactInputSingle
QUOTER_V2_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "internalType": "struct IQuoterV2.QuoteExactInputSingleParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
            {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

# Decimals for known stablecoins / wrapped tokens
DECIMALS = {
    "USDT": 18,
    "USDC": 18,
    "BUSD": 18,
    "BNB": 18,
    "WBNB": 18,
    "ETH": 18,
    "BTCB": 18,
    "CAKE": 18,
    "XRP": 18,
    "LINK": 18,
    "DOT": 18,
    "ADA": 18,
    "DOGE": 18,
    "TRX": 18,
    "AVAX": 18,
    "MATIC": 18,
    "SHIB": 18,
    "LTC": 18,
    "UNI": 18,
    "BCH": 18,
    "ATOM": 18,
    "NEAR": 18,
    "APT": 18,
    "FIL": 18,
    "ARB": 18,
    "OP": 18,
    "SAND": 18,
    "MANA": 18,
    "AXS": 18,
    "GMT": 18,
    "APE": 18,
    "SUI": 18,
    "SOL": 18,
    "RENDER": 18,
    "PYTH": 6,   # PYTH on BSC uses 6 decimals
    "JUP": 6,
    "RAY": 6,
}


class Quoter:
    """Query PancakeSwap V3 QuoterV2 for expected swap output."""

    def __init__(self, rpc_url: str = BSC_RPC_URL, wallet_address: str | None = None) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.wallet_address = wallet_address
        self._connected = self.w3.is_connected()
        if not self._connected:
            logger.error("Cannot connect to BSC RPC: %s", rpc_url)
        self.quoter = self.w3.eth.contract(address=Web3.to_checksum_address(PCS_V3_QUOTER_V2), abi=QUOTER_V2_ABI)

    async def estimate_slippage_single(
        self,
        from_symbol: str,
        to_symbol: str,
        amount_in: float,
        from_addr: str | None = None,
        to_addr: str | None = None,
        price_map: dict[str, dict[str, Any]] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Estimate output for a single pool swap across all fee tiers.

        price_map: {symbol: {price: float}} — CMC USD prices for slippage baseline.
        Uses USD-equivalent ideal output instead of raw amount_in, so slippage is
        accurate even when token values differ wildly (e.g. BNB~$300 vs USDT~$1).

        Returns best {amount_out, fee_tier, slippage_pct, status}.
        """
        if not self._connected:
            return {"error": "RPC not connected", "slippage_pct": 1.0, "status": "rpc_error"}
        if not from_addr or not to_addr:
            return {"error": "Missing token addresses for quote", "slippage_pct": 1.0, "status": "missing_addresses"}

        from_decimals = DECIMALS.get(from_symbol.upper(), 18)
        amount_in_wei = int(amount_in * (10 ** from_decimals))

        if amount_in_wei == 0:
            logger.warning("quote: amount_in is 0 for %s→%s", from_symbol, to_symbol)
            return {"error": "amount_in is zero", "slippage_pct": 1.0, "status": "zero_input"}

        best = {"amount_out": 0, "fee_tier": 0, "slippage_pct": 1.0, "status": "no_liquidity"}

        # Compute USD-equivalent ideal output so slippage baseline is currency-agnostic
        _has_price_data = False
        ideal_out: float | None = None
        if price_map:
            from_price = price_map.get(from_symbol.upper(), {}).get("price")
            to_price = price_map.get(to_symbol.upper(), {}).get("price")
            if from_price and to_price and from_price > 0 and to_price > 0:
                ideal_out_usd = amount_in * from_price          # USD value of what we're spending
                ideal_out = ideal_out_usd / to_price             # expected output in to_token units
                _has_price_data = True

        from_addr_cs = Web3.to_checksum_address(from_addr)
        to_addr_cs = Web3.to_checksum_address(to_addr)

        for fee in PCS_FEE_TIERS:
            try:
                params = {
                    "tokenIn": from_addr_cs,
                    "tokenOut": to_addr_cs,
                    "fee": fee,
                    "amountIn": amount_in_wei,
                    "sqrtPriceLimitX96": 0,
                }
                def _call_quoter(p: dict) -> list:
                    call_kwargs: dict = {}
                    if self.wallet_address:
                        call_kwargs["from"] = Web3.to_checksum_address(self.wallet_address)
                    # NOTE: web3 ContractFunction.call() does NOT accept a timeout kwarg.
                    # Timeout is controlled at the provider level or via asyncio.wait_for() outside.
                    return self.quoter.functions.quoteExactInputSingle(p).call(call_kwargs)

                result = await asyncio.wait_for(asyncio.to_thread(_call_quoter, params), timeout=15.0)
                amount_out_wei = result[0]
                to_decimals = DECIMALS.get(to_symbol.upper(), 18)
                amount_out = amount_out_wei / (10 ** to_decimals)

                if amount_out > best["amount_out"]:
                    # Slippage = (expected_usd_value - actual_usd_value) / expected_usd_value
                    if _has_price_data and ideal_out is not None and ideal_out > 0:
                        slippage = max(0.0, (ideal_out - amount_out) / ideal_out)
                    else:
                        slippage = None
                    best = {
                        "amount_out": amount_out,
                        "fee_tier": fee,
                        "slippage_pct": slippage,
                        "status": "ok" if slippage is not None else "no_price_data",
                    }

            except Exception as exc:
                logger.debug("Quoter failed for %s→%s fee=%d: %s", from_symbol, to_symbol, fee, exc)
                continue

        if best["amount_out"] == 0:
            best["status"] = "no_liquidity"

        logger.info(
            "Quote %s %.4f → %s: best fee=%d, out=%.4f, slippage=%.4f%%",
            from_symbol,
            amount_in,
            to_symbol,
            best.get("fee_tier", 0),
            best.get("amount_out", 0),
            best.get("slippage_pct", 0) * 100,
        )
        return best

    async def get_balance(self, address: str, token_addr: str | None = None) -> float:
        """Get BNB or BEP-20 token balance for an address."""
        if not self.w3.is_connected():
            return 0.0
        try:
            if token_addr is None or token_addr.upper() == WBNB.upper():
                # BNB balance
                bal = await asyncio.to_thread(
                    self.w3.eth.get_balance, Web3.to_checksum_address(address)
                )
                return bal / 1e18
            else:
                # Minimal ERC-20 balanceOf ABI
                erc20_abi = [
                    {
                        "constant": True,
                        "inputs": [{"name": "_owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"name": "balance", "type": "uint256"}],
                        "type": "function",
                    }
                ]
                token = self.w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=erc20_abi)
                bal = await asyncio.to_thread(
                    token.functions.balanceOf(Web3.to_checksum_address(address)).call
                )
                return bal / 1e18
        except Exception as exc:
            logger.warning("Balance fetch failed for %s %s: %s", address, token_addr, exc)
            return 0.0