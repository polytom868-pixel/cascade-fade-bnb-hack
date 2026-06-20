#!/usr/bin/env python3
"""
Register agent wallet on-chain for DoraHacks BNB Hack competition.

Requires:
    - web3.py
    - BNB for gas in the wallet

Usage:
    python scripts/register_agent.py
"""

import json
import os
import sys
from pathlib import Path

from web3 import Web3


# Configuration
CHAIN_ID = 56  # BSC Mainnet
RPC_URL = "https://bscrpc.pancakeswap.finance"
CONTRACT_ADDRESS = "0x212c61b9b72c95d95bf29cf032f5e5635629aed5"
WALLET_ADDRESS = "0x3EE70657C1331bd5C53D360EA6e7BB560D4D3d18"
SECRETS_FILE = Path(".kimchi/secrets/bsc_wallet.json")

# Generic registration ABI - covers common patterns
REGISTRATION_ABI = [
    {
        "name": "register",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": []
    },
    {
        "name": "register",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "_agent", "type": "address"}
        ],
        "outputs": []
    },
    {
        "name": "registerAgent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "_agent", "type": "address"}
        ],
        "outputs": []
    },
    {
        "name": "registerAgent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": []
    },
]


def load_private_key() -> str:
    """Load private key from environment variable or secrets file."""
    # Try environment variable first
    private_key = os.environ.get("PRIVATE_KEY")
    if private_key:
        return private_key

    # Try secrets file
    if SECRETS_FILE.exists():
        with open(SECRETS_FILE) as f:
            secrets = json.load(f)
            private_key = secrets.get("private_key") or secrets.get("PRIVATE_KEY")
            if private_key:
                return private_key

    raise ValueError(
        "Private key not found. Set PRIVATE_KEY env var or create "
        f"{SECRETS_FILE} with 'private_key' field."
    )


def get_contract_function(w3: Web3, contract) -> callable:
    """Try different registration function signatures to find a valid one."""
    # Try register() - no args
    try:
        fn = contract.functions.register()
        # Verify it can be built (will fail if wrong signature)
        fn.build_transaction({"from": Web3.to_checksum_address(WALLET_ADDRESS)})  # type: ignore
        return fn, "register()"  # type: ignore[reportGeneralTypeIssues,reportAttributeAccessIssue]
    except Exception:
        pass

    # Try register(_agent) with our address
    try:
        fn = contract.functions.register(WALLET_ADDRESS)
        fn.build_transaction({"from": WALLET_ADDRESS})
        return fn, "register(address)"
    except Exception:
        pass

    # Try registerAgent(_agent)
    try:
        fn = contract.functions.registerAgent(WALLET_ADDRESS)
        fn.build_transaction({"from": WALLET_ADDRESS})
        return fn, "registerAgent(address)"
    except Exception:
        pass

    # Try registerAgent() - no args
    try:
        fn = contract.functions.registerAgent()
        fn.build_transaction({"from": WALLET_ADDRESS})
        return fn, "registerAgent()"
    except Exception:
        pass

    raise ValueError(
        "Could not find a compatible registration function on the contract. "
        "The contract may use a different registration pattern."
    )


def register_agent():
    """Main registration function."""
    print("=" * 60)
    print("DoraHacks BNB Hack - Agent Registration")
    print("=" * 60)

    # Connect to BSC
    print(f"\n[1] Connecting to BSC via {RPC_URL}...")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("ERROR: Failed to connect to BSC")
        sys.exit(1)
    print(f"    Connected! Chain ID: {w3.eth.chain_id}")

    # Load wallet
    print("\n[2] Loading wallet...")
    private_key = load_private_key()
    print(f"    Wallet: {WALLET_ADDRESS}")

    # Verify wallet balance
    balance = w3.eth.get_balance(Web3.to_checksum_address(WALLET_ADDRESS))
    balance_bnb = w3.from_wei(balance, "ether")
    print(f"    Balance: {balance_bnb:.6f} BNB")

    if balance == 0:
        print("\nWARNING: Wallet has 0 BNB. Transaction will fail without gas!")
        print("Please fund your wallet with BNB before proceeding.")

    # Load contract
    print("\n[3] Loading competition contract...")
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT_ADDRESS),
        abi=REGISTRATION_ABI
    )
    print(f"    Contract: {CONTRACT_ADDRESS}")

    # Get the correct registration function
    print("\n[4] Finding compatible registration function...")
    fn, fn_sig = get_contract_function(w3, contract)
    print(f"    Using: {fn_sig}")

    # Build transaction
    print("\n[5] Building transaction...")
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(WALLET_ADDRESS))
    gas_price = w3.eth.gas_price

    tx_params = {
        "from": WALLET_ADDRESS,
        "nonce": nonce,
        "gasPrice": gas_price,
        "chainId": CHAIN_ID,
    }

    # Estimate gas
    try:
        gas_estimate = fn.estimate_gas(tx_params)
        tx_params["gas"] = int(gas_estimate * 1.2)  # Add 20% buffer
    except Exception as e:
        print(f"    Warning: Gas estimation failed: {e}")
        tx_params["gas"] = 200000  # Fallback estimate

    tx = fn.build_transaction(tx_params)
    gas_cost_wei = tx["gas"] * tx["gasPrice"]
    gas_cost_bnb = w3.from_wei(gas_cost_wei, "ether")

    print(f"    Nonce: {nonce}")
    print(f"    Gas Price: {w3.from_wei(gas_price, 'gwei'):.2f} gwei")
    print(f"    Gas Limit: {tx['gas']}")
    print(f"    Estimated Gas Cost: {gas_cost_bnb:.6f} BNB")

    # Sign transaction
    print("\n[6] Signing transaction...")
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)
    print("    Transaction signed successfully")

    # Send transaction
    print("\n[7] Sending transaction...")
    try:
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        tx_hash_hex = tx_hash.hex()
    except Exception as e:
        print(f"ERROR: Failed to send transaction: {e}")
        sys.exit(1)

    print(f"    Transaction submitted!")
    print(f"\n{'=' * 60}")
    print("TRANSACTION HASH")
    print(f"{'=' * 60}")
    print(f"  {tx_hash_hex}")
    print(f"\n{'=' * 60}")
    print("BSCSCAN LINK")
    print(f"{'=' * 60}")
    print(f"  https://bscscan.com/tx/{tx_hash_hex}")

    # Wait for receipt
    print(f"\n{'=' * 60}")
    print("WAITING FOR CONFIRMATION...")
    print(f"{'=' * 60}")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.get("status") == 1:
            print(f"  SUCCESS! Transaction confirmed in block {receipt.get('blockNumber')}")
        else:
            print("  WARNING: Transaction failed on-chain!")
    except Exception as e:
        print(f"  Note: Could not wait for confirmation: {e}")
        print("  Check BSCScan to verify transaction status.")

    print(f"\n{'=' * 60}")
    print("DONE")
    print(f"{'=' * 60}")

    return tx_hash_hex


if __name__ == "__main__":
    try:
        register_agent()
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)