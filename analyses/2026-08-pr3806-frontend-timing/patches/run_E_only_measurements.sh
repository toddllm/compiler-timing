#!/bin/bash
# E-only measurement sweep, pod-side.
#
# Preconditions (done manually before running):
#   1. torch-spyre-E worktree exists at pristine a9316b381:
#        cd ~/pr3806/torch-spyre && git worktree add ../torch-spyre-E a9316b381
#   2. dedup_constants_E_only.py is placed at:
#        ~/pr3806/torch-spyre-E/torch_spyre/_inductor/dedup_constants.py
#      (via cp overwrite of the pristine file).
#   3. The venv is rebound to the worktree, EITHER by editing the
#      __editable__ pth to point at torch-spyre-E, or by installing
#      into a fresh venv rooted at torch-spyre-E.
#
# What this script does:
#   For each Lk in {1024, 4096, 8192}, for each mode in {diag-off,
#   diag-on}, runs 3 cold samples via workload_harness.py. Writes
#   per-sample JSONs to $DATA_DIR.
#
# We DO NOT run this script until the pre-conditions above are met.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre-E}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness.py}
DATA=${DATA_DIR:-$WORKDIR/data-E-only}
mkdir -p "$DATA"

cd "$CHECKOUT"
source .venv/bin/activate

POINTS=(
  "512 1024"
  "512 4096"
  "512 8192"
)

run_one() {
    local mode=$1 Lq=$2 Lk=$3 idx=$4
    if [ "$mode" = "on" ]; then
        export TORCH_SPYRE_DEDUP_DIAG=1
        export SPYRE_DEDUP_DIAG_OUT=$DATA/dedup-diag-${Lq}x${Lk}-run${idx}.json
    else
        unset TORCH_SPYRE_DEDUP_DIAG
        unset SPYRE_DEDUP_DIAG_OUT
    fi
    export TORCH_SPYRE_TIMING=1
    export SPYRE_TIMING_OUT=$DATA/timing-${mode}-${Lq}x${Lk}-run${idx}.json
    export TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor_E_${mode}_${Lq}x${Lk}_r${idx}
    rm -rf "$TORCHINDUCTOR_CACHE_DIR" "$SPYRE_TIMING_OUT"
    [ "$mode" = "on" ] && rm -f "$SPYRE_DEDUP_DIAG_OUT"
    echo "[$(date -Is)] mode=$mode Lq=$Lq Lk=$Lk run=$idx START"
    local T0=$(date +%s)
    timeout 3600 python "$HARNESS" --Lq "$Lq" --Lk "$Lk" --out "$SPYRE_TIMING_OUT" \
      >>"$DATA/run-${mode}-${Lq}x${Lk}.log" 2>&1
    local RC=$?
    local T1=$(date +%s)
    echo "[$(date -Is)] mode=$mode Lq=$Lq Lk=$Lk run=$idx DONE rc=$RC elapsed=$((T1-T0))s"
}

for point in "${POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    for mode in off on; do
        for i in 1 2 3; do
            run_one "$mode" "$Lq" "$Lk" "$i"
        done
    done
done
echo ==DONE==
