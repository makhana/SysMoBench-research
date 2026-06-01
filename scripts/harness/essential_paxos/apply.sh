#!/usr/bin/env bash
# Apply the essential_paxos Python tracing overlay to a clean upstream copy.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
REPO_PATH="${REPO_PATH:-$PROJECT_ROOT/artifacts/essential_paxos/paxos}"
SOURCE="$REPO_PATH/paxos/essential.py"
ARTIFACT_DIR="$PROJECT_ROOT/artifacts/essential_paxos"

if [[ ! -f "$SOURCE" ]]; then
  echo "ERROR: cocagne/paxos source not found at $SOURCE" >&2
  exit 1
fi

cp "$SCRIPT_DIR/tla_trace.py" "$REPO_PATH/paxos/tla_trace.py"
cp "$SCRIPT_DIR/artifact-run.sh" "$ARTIFACT_DIR/run.sh"
cp "$PROJECT_ROOT/tla_eval/tasks/essential_paxos/INSTRUMENTATION.md" \
  "$ARTIFACT_DIR/INSTRUMENTATION.md"

if grep -q 'from paxos import tla_trace' "$SOURCE"; then
  echo "[apply.sh] instrumentation patch already applied" >&2
else
  patch --forward --silent -l -p1 -d "$REPO_PATH" \
    < "$SCRIPT_DIR/instrumentation.patch"
  echo "[apply.sh] applied instrumentation patch" >&2
fi
