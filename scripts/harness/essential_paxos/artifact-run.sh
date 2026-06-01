#!/usr/bin/env bash
# Copied to artifacts/essential_paxos/run.sh by apply.sh.

set -euo pipefail

ARTIFACT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$ARTIFACT_DIR/../.." && pwd)

exec bash "$PROJECT_ROOT/scripts/harness/essential_paxos/run.sh"
