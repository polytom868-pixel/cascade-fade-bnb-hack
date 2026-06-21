#!/usr/bin/env bash
# Inner loop script used by start_agent.sh inside tmux
set -e
MODE="${1:-paper}"
cd "$(dirname "$0")/.."

export CMC_API_KEY="${CMC_API_KEY:-}"
export TWAK_WALLET_PASSWORD="${TWAK_WALLET_PASSWORD:-}"

exec python3 -m src.agent --mode "$MODE" --cash 1000 --interval 5 --cycles 0 2>&1 | tee -a logs/paper_run_live.tmux.log
