#!/usr/bin/env bash
set -euo pipefail
# Safe restart wrapper for CascadeFade agent inside tmux
# Usage: bash scripts/start_agent.sh [paper|live]

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

MODE="${1:-paper}"
SESSION="cascade-fade"

# Kill existing session if present
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Source env
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# Run agent in tmux (survives bash tool timeouts)
tmux new-session -d -s "$SESSION" "bash scripts/agent_loop.sh $MODE"

echo "Agent started in tmux session: $SESSION"
echo "Attach: tmux attach -t $SESSION"
echo "Monitor: tail -f logs/paper_run_live.tmux.log"
