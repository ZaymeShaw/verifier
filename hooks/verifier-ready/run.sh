#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec bash "$ROOT/run.sh" python "$ROOT/hooks/verifier-ready/gate.py" "$@"
