#!/usr/bin/env bash
# scripts/harness/essential_paxos/run.sh — drive the cocagne/paxos
# instrumentation harness and emit canonical NDJSON traces.
#
# Unlike raftkvs's run.sh, no in-place patching is needed: cocagne's
# `essential.py` exposes an abstract `Messenger` interface that our
# `HarnessMessenger` implements externally. The clone is read-only.
#
# Usage (from project root):
#     bash scripts/harness/essential_paxos/run.sh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)

REPO_PATH="${REPO_PATH:-$PROJECT_ROOT/data/repositories/cocagne_paxos}"
TRACES_DIR="${TRACES_DIR:-$PROJECT_ROOT/artifacts/essential_paxos/traces}"

if [[ ! -d "$REPO_PATH/paxos" ]]; then
  echo "ERROR: cocagne/paxos clone not found at $REPO_PATH" >&2
  echo "Bootstrap with:" >&2
  echo "    git clone https://github.com/cocagne/paxos.git $REPO_PATH" >&2
  echo "    (cd $REPO_PATH && git checkout <commit-from-task.yaml>)" >&2
  exit 1
fi

mkdir -p "$TRACES_DIR"

echo "[run.sh] REPO_PATH:   $REPO_PATH" >&2
echo "[run.sh] TRACES_DIR:  $TRACES_DIR" >&2

export PYTHONPATH="$REPO_PATH:${PYTHONPATH:-}"
export TRACES_DIR

python3 "$SCRIPT_DIR/run.py"

# Quick sanity report — each scenario should end with a HandleAccepted whose
# state contains final_value (i.e. consensus was reached).
echo "[run.sh] trace summary:" >&2
for f in "$TRACES_DIR"/trace_*.ndjson; do
  total=$(wc -l < "$f")
  resolved=$(grep -c '"final_value": [^n]' "$f" || true)
  printf "    %-50s %s events, %s resolution(s)\n" \
    "$(basename "$f")" "$total" "$resolved" >&2
done

echo "[run.sh] done" >&2