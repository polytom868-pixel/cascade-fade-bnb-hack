# Wave 1: Safety + Bug Fixes (P0)

| Agent | Target File | Fixes | Verify |
|---|---|---|---|
| W1-A1 | `src/portfolio.py` | PRAGMA busy_timeout=30000, BEGIN IMMEDIATE | `python3 -c "import ast; ast.parse(open('src/portfolio.py').read())"` |
| W1-A2 | `src/cache.py` | PRAGMA busy_timeout=30000, BEGIN IMMEDIATE, CACHE_TTL=1800, index, TTL GC | `python3 -c "import ast; ast.parse(open('src/cache.py').read())"` |
| W1-A3 | `src/log.py` | PRAGMA busy_timeout=30000, BEGIN IMMEDIATE | `python3 -c "import ast; ast.parse(open('src/log.py').read())"` |
| W1-A4 | `src/signal.py` | Fix max() generator, pre-reverse map for decision | `python3 -c "import ast; ast.parse(open('src/signal.py').read())"` |
| W1-A5 | `src/utils.py`, `src/config.py` | Remove SELECT 1, add apply_db_pragmas, ALLOWLIST copy, CACHE_TTL | `python3 -c "import ast; ast.parse(open('src/utils.py').read()); ast.parse(open('src/config.py').read())"` |

After Wave 1 completes:
- git add explicitly by filename
- git commit
- Then Wave 2
