#!/usr/bin/env bash
# Run a single cold-compile sample against an isolated checkout.
#
# Usage:
#   run_isolated_sample.sh <tree-dir> <harness.py> <out.json> [extra harness args...]

set -euo pipefail

TREE="${1:?tree-dir required}"
HARNESS="${2:?harness.py required}"
OUT="${3:?output JSON path required}"
shift 3

BASE_VENV="${BASE_VENV:-$HOME/pr3806/torch-spyre/.venv}"
SHIM_DIR="${SHIM_DIR:-$HOME/skill-runs/skill-scripts}"

TAG=$(basename "$OUT" .json)
CACHE_DIR="/tmp/torchinductor_iso_${TAG}_$$"
rm -rf "$CACHE_DIR"
export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
export TORCH_SPYRE_TIMING=1

# shellcheck disable=SC1090
source "$BASE_VENV/bin/activate"

PYTHONPATH="$TREE:$SHIM_DIR" python "$SHIM_DIR/shim_runner.py" "$HARNESS" \
    "$@" --out "$OUT"

rm -rf "$CACHE_DIR"
