#!/usr/bin/env bash
# Pilot driver: one sample per shape at five representative shapes.
# Used to validate the framework end-to-end before committing to the
# full 3-sample sweep.
#
# Shape selection (fixed by the review — do not change without a
# corresponding review):
#   flash 512x1024
#   flash 512x8192
#   flash 1024x8192
#   mlp   L=2   (small)
#   mlp   L=32  (large)
#
# Environment override: same as sweep_driver.sh.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO to the instrumented torch-spyre repo root}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/pilot}"
: "${MODE:=stop}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA_DIR"

MLP_N_IN=1024
MLP_N_HIDDEN=2048

run() {
    local tag="$1"; shift
    local out="$1"; shift
    local cache="$1"; shift
    local rc
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"
    echo "=== [$(date -Is)] $tag ==="
    set +e
    python3 "$HARNESS" --mode "$MODE" --out "$out" "$@" 2>&1 | tee "${out%.json}.log"
    rc=${PIPESTATUS[0]}
    set -e
    if [[ $rc -eq 0 ]]; then
        echo "OK   $tag rc=0"
    else
        echo "FAIL $tag rc=$rc"
    fi
}

run "flash 512x1024" \
    "$DATA_DIR/flash-512x1024-run1.json"  /tmp/tsc-pilot-flash-512x1024 \
    --workload flash --Lq 512  --Lk 1024
run "flash 512x8192" \
    "$DATA_DIR/flash-512x8192-run1.json"  /tmp/tsc-pilot-flash-512x8192 \
    --workload flash --Lq 512  --Lk 8192
run "flash 1024x8192" \
    "$DATA_DIR/flash-1024x8192-run1.json" /tmp/tsc-pilot-flash-1024x8192 \
    --workload flash --Lq 1024 --Lk 8192
run "mlp L=2" \
    "$DATA_DIR/mlp-L2-w${MLP_N_HIDDEN}-run1.json" /tmp/tsc-pilot-mlp-L2 \
    --workload mlp --N-in "$MLP_N_IN" --N-hidden "$MLP_N_HIDDEN" --layers 2
run "mlp L=32" \
    "$DATA_DIR/mlp-L32-w${MLP_N_HIDDEN}-run1.json" /tmp/tsc-pilot-mlp-L32 \
    --workload mlp --N-in "$MLP_N_IN" --N-hidden "$MLP_N_HIDDEN" --layers 32

echo "=== [$(date -Is)] pilot complete"
echo "next: python3 harness/analyze_sweep.py --sweep-dir $DATA_DIR "
echo "        --out-notes /tmp/pilot-notes --out-tables /tmp/pilot-tables --strict"
