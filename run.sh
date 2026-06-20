#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Load environment
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# Python venv
if [[ -d .venv ]]; then
    source .venv/bin/activate
fi

MODE="${1:-paper}"
CASH="${2:-1000}"

echo "=== CascadeFade Agent ==="
echo "Mode: $MODE"
echo "Cash: $CASH"
echo "======================="

if command -v tmux &>/dev/null; then
    SESSION="cascadefade"
    tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION"
    tmux new-session -d -s "$SESSION" \
        "python -m src.agent --mode $MODE --cash $CASH 2>&1 | tee logs/agent.log"
    echo "Agent started in tmux session: $SESSION"
    echo "Attach: tmux attach -t $SESSION"
    echo "Logs: tail -f logs/agent.log"
else
    nohup python -m src.agent --mode "$MODE" --cash "$CASH" >logs/agent.log 2>&1 &
    echo "Agent started in background (PID $!)"
    echo "Logs: tail -f logs/agent.log"
fi
