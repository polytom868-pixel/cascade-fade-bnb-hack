"""Configuration and constants for CascadeFade."""
import os
from pathlib import Path

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
    # --- Pre-existing real tokens ---
    "BNB":   "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "WBNB":  "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "USDT":  "0x55d398326f99059fF775485246999027B3197955",
    "BUSD":  "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
    "USDC":  "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    "BTCB":  "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c",
    "ETH":   "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
    "CAKE":  "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "XRP":   "0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE",
    "LINK":  "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD",
    "DOT":   "0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402",
    "ADA":   "0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47",
    "DOGE":  "0xbA2aE424d960c26247Dd6c32edC70B295c744C43",
    "TRX":   "0xCE7de646e7208a4Ef112cb6ed5038FA6cC6b12e3",
    "AVAX":  "0x1CE0c2827e2eF14D5C4f29a091d735A204794041",
    "MATIC": "0xCC42724C6683B7E57334c4E856f4c9965ED682bD",
    "SHIB":  "0x2859e4544C4bB039668170684841cc0A1F9c7C62",
    "LTC":   "0x4338665CBB7B2485A8855A139b75D5e34AB0DB94",
    "UNI":   "0xBf5140A22578168Fd562DdcE682D461E5c1DfcC1",
    "BCH":   "0x8fF795a6F4D97E7887C79beA79aba5cc76444aDf",
    "ATOM":  "0x0Eb3a705fc54725037CC9e008bDede697f62F335",
    "NEAR":  "0x1d3582E75e3025764531c593788eC56006EB2B81",
    "APT":   "0x615Ed116D5208903f102827Aa4ce4473D6747c37",
    "FIL":   "0x0D8Ce2A99Bb6e3B7Db580eD848240e4a0F9aE153",
    "ARB":   "0xA2315cC6693242D92A622685114e2824E84B4893",
    "OP":    "0x0566C906bD9aC75B6414B486dF4ca28A3716a68B",
    "SAND":  "0x67b725d4aA8BBD53285b13FDB1e3Abd98B7418E2",
    "MANA":  "0x26433c8127e2CdEf3cE10149d64443D49324dBb4",
    "AXS":   "0x715D400F88C167884bbCc41C5FeA407ed4D2f8A0",
    "GMT":   "0x3019BF2a2eF8040C242C9a4c5c4BD4C81678a2D5",
    "APE":   "0x8f86a15EC17cb3369d8b3E666dAdBC11daA82b79",
    "SUI":   "0x8314d3831A4A6e558c3b488B185C3992Fd8AbbA5",
    "SOL":   "0x570A5D26f7765Ecb712C0924E4De545B89fD43dF",
    "RENDER":"0x8C8f03284B09Ea059F4eF1d2C15C65f1b5511f1E",
    # --- Competitor repo additions (narrative baskets) ---
    # AI Tokens
    "FET":   "0x031b41e504677879370e9dbcf937283a8691fa7f",
    "INJ":   "0xa2b726b1145a4773f68593cf171187d8ebe4d495",
    "SAHARA":"0xFDFfB411C4A70AA7C95D5C981a6Fb4Da867e1111",
    "0G":    "0x4B948d64dE1F71fCd12fB586f4c776421a35b3eE",
    "PEAQ":  "0x8b9Ee39195eA99d6ddD68030F44131116bc218F6",
    # AI Agents
    "SKYAI": "0x92aa03137385F18539301349dcfC9EbC923fFb10",
    "DEXE":  "0x6E88056E8376Ae7709496Ba64d37fa2f8015ce3e",
    "AB":    "0x95034f653d5d161890836ad2b6b8cc49d14e029a",
    "EDGE":  "0x70f2eadf1ca1969ff42b0c78e9da519e8937cbaf",
    "GENIUS":"0x1F12B85aAC097E43Aa1555b2881E98a51090e9A6",
    # RWA
    "PENDLE":"0xb3Ed0A426155B79B898849803E3B36552f7ED507",
    "PLUME": "0x5aFadCd1E8E3CA78Ee2D37100102f2aec8Bc0Aa8",
    "FDUSD": "0xc5f0f7b66764F6ec8C8Dff7BA683102295E16409",
    # DePIN
    "AIOZ":  "0x33d08D8C7a168333a85285a68C0042b39fC3741D",
    "TAC":   "0x1219c409fabe2c27bd0d1a565daeed9bd9f271de",
    "IRYS":  "0x91152B4Ef635403efBAe860edD0F8c321d7c035d",
    # Meme
    "BONK":  "0xA697e272a73744b343528C3Bc4702F2565b2F422",
    "PENGU": "0x6418c0dd099a9fda397c766304cdd918233e8847",
    "FLOKI": "0xfb5b838b6cfeedc2873ab27866079ac55363d37e",
    # Privacy
    "ZEC":   "0x1ba42e5193dfa8b03d15dd1b86a3113bbbef8eeb",
    "ROSE":  "0xF00600eBC7633462BC4F9C61eA2cE99F5AAEBd4a",
    "DUSK":  "0xb2bd0749dbe21f623d9baba856d3b0f0e1bfec9c",
    "ZAMA":  "0x6907a5986c4950bdaf2f81828ec0737ce787519f",
    # DeFi Blue
    "AAVE":  "0xfb6115445bff7b52feb98650c87f44907e58f802",
    "COMP":  "0x52ce071bd9b1c4b00a0b92d298c512478cad67e8",
    # L1/L2
    "TON":   "0x76a797a59ba2c17726896976b7b3747bfd1d220f",
    # Gaming/NFT
    "BEAM":  "0x62D0A8458eD7719FDAF978fe5929C6D342B0bFcE",
    "BTT":   "0x352Cb5E19b12FC216548a2677bD0fce83BaE434B",
    "ACH":   "0xBc7d6B50616989655AfD682fb42743507003056D",
    # BNB Chain
    "TWT":   "0x4b0f1812e5df2a09796481ff14017e6005508003",
    "ASTER": "0x000Ae314E2A2172a039B26378814C252734f556A",
    "SFP":   "0xd41fdb03ba84762dd66a0af1a6c8540ff1ba5dfb",
    # +83 tokens from PancakeSwap Extended List
    "8PAY":   "0x6eadc05928acd93efb3fa0dfbc644d96c6aa1df8",
    "ACE":    "0xc27a719105a987b4c34116223cae8bd8f8b5def4",
    "ADX":    "0x6bff4fb161347ad7de4a625ae5aa3a1ca7077819",
    "AI":     "0x2598c30330d5771ae9f983979209486ae26de875",
    "AITECH": "0x2d060ef4d6bf7f9e5edde373ab735513c0e4f944",
    "ALICE":  "0xac51066d7bec65dc4589368da368b212745d63e8",
    "ALPA":   "0xc5e6689c9c8b02be7c49912ef19e79cf24977f03",
    "ALPACA": "0x8f0528ce5ef7b51152a59745befdd91d97091d2f",
    "ALPHA":  "0xa1faa113cbe53436df28ff0aee54275c13b40975",
    "AMPL":   "0xdb021b1b247fe2f1fa57e0a87c748cc1e321f07f",
    "ANKR":   "0xf307910a4c7bbc79691fd374889b36d8531b08e3",
    "ANKRBNB":"0x52f24a5e03aee338da5fd9df68d2b6fae1178827",
    "ANKRETH":"0xe05a08226c49b636acf99c40da8dc6af83ce5bb3",
    "ANTEX":  "0xca1acab14e85f30996ac83c64ff93ded7586977c",
    "ANYMTLX":"0x5921dee8556c4593eefcfad3ca5e2f618606483b",
    "AOG":    "0x40c8225329bd3e28a043b029e0d07a5344d2c27c",
    "APX":    "0x78f5d389f5cdccfc41594abab4b0ed02f31398b3",
    "APYS":   "0x37dfacfaeda801437ff648a1559d73f4c40aacb7",
    "ARENA":  "0xcffd4d3b517b77be32c76da768634de6c738889b",
    "ARPA":   "0x6f769e65c14ebd1f68817f5f1dcdb61cfa2d6f7e",
    "ARV":    "0x6679eb24f59dfe111864aec72b443d1da666b360",
    "ASR":    "0x80d5f92c2c8c682070c95495313ddb680b267320",
    "ATA":    "0xa2120b9e674d3fc3875f415a7df52e382f141225",
    "ATM":    "0x25e9d05365c867e59c1904e7463af9f312296f9e",
    "AUTO":   "0xa184088a740c695e156f91f5cc086a06bb78b827",
    "AXL":    "0x8b1f4432f943c465a973fedc6d7aa50fc96f1f65",
    "AXLSTARS":"0xc3cac4ae38ccf6985ef9039acc1abbc874ddcbb0",
    "AXLUSDC":"0x4268b8f0b87b6eae5d897996e6b845ddbd99adf3",
    "BABYCAKE":"0xdb8d30b74bf098af214e862c90e647bbb1fcc58c",
    "BAKE":   "0xe02df9e3e622debdd69fb838bb799e3f168902c5",
    "BALBT":  "0x72faa679e1008ad8382959ff48e392042a8b06f7",
    "BAND":   "0xad6caeb32cd2c308980a548bd0bc5aa4306c6c18",
    "BAT":    "0x101d82428437127bf1608f699cd651e6abf9766e",
    "BATH":   "0x0bc89aa98ad94e6798ec822d0814d934ccd0c0ce",
    "BBADGER":"0x1f7216fdb338247512ec99715587bb97bbf96eae",
    "BBT":    "0xd48474e7444727bf500a32d5abe01943f3a59a64",
    "BCFX":   "0x045c4324039da91c52c55df5d785385aab073dcf",
    "BCOIN":  "0x00e1656e45f18ec6747f5a8496fd39b50b38396d",
    "BDIGG":  "0x5986d5c77c65e5801a5caa4fae80089f870a71da",
    "BDO":    "0x190b589cf9fb8ddeabbfeae36a813ffb2a702454",
    "BEL":    "0x8443f091997f06a61670b735ed92734f5628692f",
    "BELT":   "0xe0e514c71282b6f4e823703a39374cf58dc3ea4f",
    "BETA":   "0xbe1a001fe942f96eea22ba08783140b9dcc09d28",
    "BETH":   "0x250632378e573c6be1ac2f97fcdf00515d0aa91b",
    "BFI":    "0x81859801b01764d4f0fa5e64729f5a6c3b91435b",
    "BIFI":   "0xca3f508b8e4dd382ee878a314789373d80a5190a",
    "BITU":   "0x654a32542a84bea7d2c2c1a1ed1aaaf26888e6bd",
    "BLK":    "0x63870a18b6e42b01ef1ad8a2302ef50b7132054f",
    "BMON":   "0x08ba0619b1e7a582e0bce5bbe9843322c954c340",
    "BMXX":   "0x4131b87f74415190425ccd873048c708f8005823",
    "BNBX":   "0x1bdd3cf7f79cfb8edbb955f20ad99211551ba275",
    "BNX":    "0x5b1f874d0b0c5ee17a495cbb70ab8bf64107a3bd",
    "BONDLY": "0x5d0158a5c3ddf47d4ea4517d8db0d76aa2e87563",
    "BORING": "0xffeecbf8d7267757c2dc3d13d730e97e15bfdf7f",
    "BOXY":   "0x9f5d4479b783327b61718fa13b3a0583869a80c1",
    "BP":     "0xacb8f52dc63bb752a51186d1c55868adbffee9c1",
    "BROOBEE":"0xe64f5cb844946c1f102bd25bbd87a5ab4ae89fbe",
    "BRY":    "0xf859bf77cbe8699013d6dbc7c2b926aaf307f830",
    "BSCDEFI":"0x40e46de174dfb776bb89e04df1c47d8a66855eb3",
    "BSCPAD": "0x5a3010d4d8d3b5fb49f8b6e57fb9e48063f16700",
    "BSCX":   "0x5ac52ee5b2a633895292ff6d8a89bb9190451587",
    "BSW":    "0x965f527d9159dce6288a2219db51fc6eef120dd1",
    "BTCST":  "0x78650b139471520656b9e7aa7a5e9276814a38e9",
    "BTR":    "0x5a16e8ce8ca316407c6e6307095dc9540a8d62b3",
    "BTTOLD": "0x8595f9da7b868b1822194faed312235e43007b49",
    "BUNNY":  "0xc9849e6fdb743d08faee3e34dd2d1bc69ea11a51",
    "BURGER": "0xae9269f27437f0fcbc232d39ec814844a51d6b8f",
    "BUX":    "0x211ffbe424b90e25a15531ca322adf1559779e45",
    "C98":    "0xaec945e04baf28b135fa7c640f624f8d90f1c3a6",
    "CAPS":   "0xffba7529ac181c2ee1844548e6d7061c9a597df4",
    "CART":   "0x5c8c8d560048f34e5f7f8ad71f2f81a89dbd273e",
    "CAT":    "0x6894cde390a3f51155ea41ed24a33a4827d3063d",
    "CEEK":   "0xe0f94ac5462997d2bc57287ac3a3ae4c31345d66",
    "CGG":    "0x1613957159e9b0ac6c80e824f7eea748a32a0ae2",
    "CGPT":   "0x9840652dc04fb9db2c43853633f0f62be6f00f98",
    "CHAMP":  "0x7e9ab560d37e62883e882474b096643cab234b65",
    "CHESS":  "0x20de22029ab63cf9a7cf5feb2b737ca1ee4c82a6",
    "CHR":    "0xf9cec8d50f6c8ad3fb6dccec577e05aa32b224fe",
    "CKP":    "0x2b5d9adea07b590b638ffc165792b2c610eda649",
    "CO":     "0x936b6659ad0c1b244ba8efe639092acae30dc8d6",
    "COS":    "0x96dd399f9c3afda1f194182f71600f1b65946501",
    "CREAM":  "0xd4cb328a82bdf5f03eb737f37fa6b370aef3e888",
    "CSIX":   "0x04756126f044634c9a0f0e985e60c88a51acc206",
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
ALLOWLIST_TO_TOKEN_ADDRESS = ALLOWLIST
REGIME_SIZING = {"RISK_ON": 1.0, "TRANSITION": 0.6, "RISK_OFF": 0.3}
