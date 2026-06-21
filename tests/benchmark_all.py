"""Run all micro-benchmarks and print a unified JSON report."""
import asyncio
import importlib
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODULES = [
    "tests.microbench_cmc",
    "tests.microbench_signal",
    "tests.microbench_storage",
    "tests.microbench_twak",
    "tests.microbench_zero_copy",
]


async def run_all() -> dict:
    all_results: list[dict] = []
    errors: list[dict] = []
    for mod_name in MODULES:
        try:
            mod = importlib.import_module(mod_name)
            rows = await mod.bench()
            all_results.extend(rows)
        except Exception as exc:
            errors.append({
                "module": mod_name,
                "error": str(exc),
                "trace": traceback.format_exc(),
            })
    return {"results": all_results, "errors": errors}


if __name__ == "__main__":
    report = asyncio.run(run_all())
    print(json.dumps(report, indent=2, default=str))
