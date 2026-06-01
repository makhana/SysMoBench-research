#!/usr/bin/env bash
# scripts/harness/essential_paxos/run.sh - drive the cocagne/paxos
# instrumentation harness and emit canonical NDJSON traces.
#
# Usage (from project root):
#     bash scripts/harness/essential_paxos/run.sh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)

REPO_PATH="${REPO_PATH:-$PROJECT_ROOT/artifacts/essential_paxos/paxos}"
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

"$SCRIPT_DIR/apply.sh"

export PYTHONPATH="$REPO_PATH:${PYTHONPATH:-}"
export TRACES_DIR

python3 "$SCRIPT_DIR/run.py"
python3 "$SCRIPT_DIR/validate_traces.py" "$TRACES_DIR"

echo "[run.sh] trace summary:" >&2
for f in "$TRACES_DIR"/trace_*.ndjson; do
  total=$(wc -l < "$f")
  printf "    %-50s %s events\n" "$(basename "$f")" "$total" >&2
done

echo "[run.sh] done" >&2
