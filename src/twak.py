"""Trust Wallet Agent Kit (TWAK) CLI subprocess wrapper."""
import asyncio
import json
import logging
import os
import shlex
from typing import Any

from src.config import BSC_CHAIN_ID
from src.utils import parse_twak_json_output, parse_tx_hash_from_stdout

logger = logging.getLogger("cascadefade.twak")


class TWAKExecutor:
    """Execute swaps and queries via the `twak` CLI."""

    def __init__(self, password: str | None = None) -> None:
        self.password = password or os.getenv("TWAK_WALLET_PASSWORD", "")
        self._nonce_lock = asyncio.Lock()

    def _build_cmd(
        self,
        subcommand: list[str],
        chain: str = "bsc",
        json_output: bool = True,
        quote_only: bool = False,
        slippage: float | None = None,
    ) -> list[str]:
        cmd = ["twak"] + subcommand
        cmd += ["--chain", chain]
        if json_output:
            cmd += ["--json"]
        if quote_only:
            cmd += ["--quote-only"]
        if slippage is not None:
            cmd += ["--slippage", str(slippage)]
        if self.password:
            cmd += ["--password", self.password]
        return cmd

    async def _run(self, cmd: list[str], timeout: int = 120) -> dict[str, Any]:
        """Run a TWAK command and parse output."""
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        logger.info("TWAK cmd: %s", cmd_str)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")

            result: dict[str, Any] = {"returncode": proc.returncode, "stdout": stdout, "stderr": stderr}

            # Try JSON parsing first
            if stdout.strip():
                try:
                    parsed = parse_twak_json_output(stdout)
                    result["data"] = parsed
                except ValueError:
                    # Fallback: look for tx hash
                    tx_hash = parse_tx_hash_from_stdout(stdout)
                    if tx_hash:
                        result["tx_hash"] = tx_hash
                        result["data"] = {"txHash": tx_hash}
                    else:
                        result["data"] = {"raw": stdout[:500]}

            if proc.returncode != 0:
                result["error"] = stderr[:500] if stderr else "twak command failed"
                logger.error("TWAK failed (rc=%d): %s", proc.returncode, result.get("error"))
            else:
                logger.info("TWAK success")

            return result

        except asyncio.TimeoutError:
            logger.error("TWAK command timed out after %ds", timeout)
            return {"error": f"timeout after {timeout}s", "returncode": -1}
        except FileNotFoundError:
            logger.error("`twak` CLI not found. Install with: npm install -g @trustwallet/cli")
            return {"error": "twak CLI not found", "returncode": -1}
        except Exception as exc:
            logger.error("TWAK exception: %s", exc)
            return {"error": str(exc), "returncode": -1}

    async def swap(
        self,
        amount: float,
        from_token: str,
        to_token: str,
        slippage: float = 0.5,
        quote_only: bool = False,
    ) -> dict[str, Any]:
        """Execute or quote a swap via TWAK.

        Args:
            amount: Amount in from_token units.
            from_token: Symbol or contract address.
            to_token: Symbol or contract address.
            slippage: Max slippage % (default 0.5).
            quote_only: If True, preview only.
        """
        cmd = self._build_cmd(
            ["swap", str(amount), from_token, to_token],
            slippage=slippage,
            quote_only=quote_only,
        )
        return await self._run(cmd)

    async def get_balance(self, token: str | None = None) -> dict[str, Any]:
        """Get wallet balance. If token is None, returns BNB + all token balances."""
        cmd = ["twak", "wallet", "balance"]
        if token:
            cmd.append(token)
        cmd += ["--chain", "bsc", "--json"]
        return await self._run(cmd)

    async def get_address(self) -> str | None:
        """Get the agent wallet address."""
        result = await self._run(["twak", "wallet", "address", "--json"])
        data = result.get("data", {})
        if isinstance(data, dict):
            return data.get("address") or data.get("wallet_address")
        return None

    async def compete_register(self) -> dict[str, Any]:
        """Register wallet for BNB Hack competition."""
        return await self._run(["twak", "compete", "register", "--json"])

    async def get_portfolio(self) -> dict[str, Any]:
        """Get full portfolio overview."""
        return await self._run(["twak", "wallet", "portfolio", "--json"])


# Alias for backward compatibility
TwakClient = TWAKExecutor
