"""Configuration and constants for CascadeFade."""
import os
from pathlib import Path

CACHE_TTL_SECONDS = 1800  # match trade interval

# ── Base paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = LOGS_DIR / "cascade_fade.db"

# ── CMC API ─────────────────────────────────────────────────────────────
CMC_BASE_URL = "https://pro-api.coinmarketcap.com"
CMC_TRIAL_URL = "https://pro-api.coinmarketcap.com/trial-pro-api"
CMC_TIMEOUT = 30
CMC_RETRIES = 3
CMC_RETRY_BACKOFF = 1.5

# Endpoints
CMC_QUOTES_LATEST = "/v2/cryptocurrency/quotes/latest"
CMC_FEAR_GREED = "/v3/fear-and-greed/latest"
CMC_DEX_TRENDING = "/v1/dex/tokens/trending/list"
CCM_DEX_PAIRS_QUOTES = "/v4/dex/pairs/quotes/latest"

# ── BSC / PancakeSwap ───────────────────────────────────────────────────
BSC_CHAIN_ID = 56
BSC_RPC_URL = os.getenv("BNB_RPC_URL", "https://bscrpc.pancakeswap.finance")

PCS_V3_SMART_ROUTER = "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4"
PCS_V3_QUOTER_V2 = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
PCS_V3_SWAP_ROUTER = "0x1b81D678ffb9C0263b24A97847620C99d213eB14"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

PCS_FEE_TIERS = [100, 500, 3000, 10000]  # 0.01%, 0.05%, 0.25%, 1%

# Competition
COMPETITION_CONTRACT = "0x212c61b9b72c95d95bf29cf032f5e5635629aed5"
ERC8004_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"

# ── Risk constants ──────────────────────────────────────────────────────
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "2"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.10"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.05"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.10"))
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "0.25"))
PORTFOLIO_FLOOR_USD = 5.0
HEARTBEAT_SIZE_USD = float(os.getenv("HEARTBEAT_SIZE_USD", "5"))
MIN_TRADE_SIZE_USD = 1.0  # was 5.0 — per-token minimum for basket trades
MAX_SLIPPAGE_PCT = float(os.getenv("MAX_SLIPPAGE_PCT", "0.01"))
HEARTBEAT_HOUR_UTC = int(os.getenv("HEARTBEAT_HOUR_UTC", "20"))
TRADE_INTERVAL_MINUTES = int(os.getenv("TRADE_INTERVAL_MINUTES", "30"))
MAX_HOLD_HOURS = 48
ROUND_TRIP_COST_PCT = 0.006  # 0.6% estimated gas + swap fee
AGENT_MODE = os.getenv("AGENT_MODE", "paper")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
CASH_CURRENCY = "USDT"
RISK_CURRENCY = "WBTC"

# ── BEP-20 token allowlist ─────────────────────────────────────────────────
# Sources:
#   - Pre-existing real tokens (USDT, USDC, BTCB, ETH, CAKE, LINK, etc.)
#   - Competitor repo (asbestos22/narrative-rotation-index @ b1c4c3d) NARRATIVE_BASKETS
#     narratives: AI Tokens, AI Agents, RWA, DePIN, Meme, Privacy, DeFi Blue,
#     L1/L2, Gaming/NFT, BNB Chain
# Removed fakes: PYTH (0xD3... fake), JUP (0x023... fake)
ALLOWLIST = {
    "0G": "0x4B948d64dE1F71fCd12fB586f4c776421a35b3eE",
    "AAVE": "0xfb6115445bff7b52feb98650c87f44907e58f802",
    "AB": "0x95034f653d5d161890836ad2b6b8cc49d14e029a",
    "ACH": "0xBc7d6B50616989655AfD682fb42743507003056D",
    "ADA": "0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47",
    "AIOZ": "0x33d08D8C7a168333a85285a68C0042b39fC3741D",
    "APE": "0x8f86a15EC17cb3369d8b3E666dAdBC11daA82b79",
    "ASTER": "0x000Ae314E2A2172a039B26378814C252734f556A",
    "ATOM": "0x0Eb3a705fc54725037CC9e008bDede697f62F335",
    "AVAX": "0x1CE0c2827e2eF14D5C4f29a091d735A204794041",
    "AXL": "0x8b1f4432f943c465a973fedc6d7aa50fc96f1f65",
    "AXS": "0x715D400F88C167884bbCc41C5FeA407ed4D2f8A0",
    "BAT": "0x101d82428437127bf1608f699cd651e6abf9766e",
    "BCH": "0x8fF795a6F4D97E7887C79beA79aba5cc76444aDf",
    "BEAM": "0x62D0A8458eD7719FDAF978fe5929C6D342B0bFcE",
    "BONK": "0xA697e272a73744b343528C3Bc4702F2565b2F422",
    "BTT": "0x352Cb5E19b12FC216548a2677bD0fce83BaE434B",
    "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "COMP": "0x52ce071bd9b1c4b00a0b92d298c512478cad67e8",
    "DEXE": "0x6E88056E8376Ae7709496Ba64d37fa2f8015ce3e",
    "DOGE": "0xbA2aE424d960c26247Dd6c32edC70B295c744C43",
    "DOT": "0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402",
    "DUSK": "0xb2bd0749dbe21f623d9baba856d3b0f0e1bfec9c",
    "EDGE": "0x70f2eadf1ca1969ff42b0c78e9da519e8937cbaf",
    "ETH": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
    "FDUSD": "0xc5f0f7b66764F6ec8C8Dff7BA683102295E16409",
    "FET": "0x031b41e504677879370e9dbcf937283a8691fa7f",
    "FIL": "0x0D8Ce2A99Bb6e3B7Db580eD848240e4a0F9aE153",
    "FLOKI": "0xfb5b838b6cfeedc2873ab27866079ac55363d37e",
    "GENIUS": "0x1F12B85aAC097E43Aa1555b2881E98a51090e9A6",
    "INJ": "0xa2b726b1145a4773f68593cf171187d8ebe4d495",
    "IRYS": "0x91152B4Ef635403efBAe860edD0F8c321d7c035d",
    "LINK": "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD",
    "LTC": "0x4338665CBB7B2485A8855A139b75D5e34AB0DB94",
    "PEAQ": "0x8b9Ee39195eA99d6ddD68030F44131116bc218F6",
    "PENDLE": "0xb3Ed0A426155B79B898849803E3B36552f7ED507",
    "PENGU": "0x6418c0dd099a9fda397c766304cdd918233e8847",
    "PLUME": "0x5aFadCd1E8E3CA78Ee2D37100102f2aec8Bc0Aa8",
    "ROSE": "0xF00600eBC7633462BC4F9C61eA2cE99F5AAEBd4a",
    "SAHARA": "0xFDFfB411C4A70AA7C95D5C981a6Fb4Da867e1111",
    "SFP": "0xd41fdb03ba84762dd66a0af1a6c8540ff1ba5dfb",
    "SHIB": "0x2859e4544C4bB039668170684841cc0A1F9c7C62",
    "SKYAI": "0x92aa03137385F18539301349dcfC9EbC923fFb10",
    "TAC": "0x1219c409fabe2c27bd0d1a565daeed9bd9f271de",
    "TON": "0x76a797a59ba2c17726896976b7b3747bfd1d220f",
    "TRX": "0xCE7de646e7208a4Ef112cb6ed5038FA6cC6b12e3",
    "TWT": "0x4b0f1812e5df2a09796481ff14017e6005508003",
    "UNI": "0xBf5140A22578168Fd562DdcE682D461E5c1DfcC1",
    "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    "USDT": "0x55d398326f99059fF775485246999027B3197955",
    "XRP": "0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE",
    "ZAMA": "0x6907a5986c4950bdaf2f81828ec0737ce787519f",
    "ZEC": "0x1ba42e5193dfa8b03d15dd1b86a3113bbbef8eeb",
    "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
}
# Narrative baskets — each narrative holds 5 tokens from the ALLOWLIST above
NARRATIVE_BASKETS = {
    "AI Tokens":  ["INJ", "FET", "COMP", "PENDLE", "FIL"],
    "AI Agents":  ["SKYAI", "DEXE", "AB", "PENDLE", "COMP"],
    "RWA":        ["USDC", "FDUSD", "PENDLE", "COMP", "CAKE"],
    "DePIN":      ["FIL", "PEAQ", "CAKE", "COMP", "PENDLE"],
    "Meme":       ["DOGE", "SHIB", "BONK", "PENGU", "FLOKI"],
    "Privacy":    ["ZEC", "ROSE", "DUSK", "COMP", "CAKE"],
    "DeFi Blue":  ["AAVE", "UNI", "CAKE", "COMP", "PENDLE"],
    "L1/L2":      ["ETH", "AVAX", "ADA", "DOT", "TON"],
    "Gaming/NFT": ["AXS", "APE", "CAKE", "COMP", "PENDLE"],
    "BNB Chain":  ["CAKE", "TWT", "COMP", "PENDLE", "DEXE"],
}

# CMC internal IDs for the allowlist (populated at runtime if not cached)
CMC_SYMBOL_TO_ID: dict[str, int] = {}

# Aliases for backward compatibility
ALLOWLIST_TO_TOKEN_ADDRESS = ALLOWLIST.copy()
