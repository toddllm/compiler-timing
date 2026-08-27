#!/bin/bash
# Cold-compile diagnostic sweep for dedup_and_promote_constants.
#
# Prerequisites on the pod (see notes/dedup-phase2-plan.md §Instrumentation):
#   - torch-spyre checked out at a9316b381 (or a fresh detached worktree at that SHA).
#   - dedup_diagnostics.py placed at torch_spyre/_inductor/dedup_diagnostics.py.
#   - dedup_diagnostics.patch applied on top of that SHA.
#   - The existing TORCH_SPYRE_TIMING patch NOT applied simultaneously — this
#     sweep uses the diagnostic path only, so we can attribute the added
#     wall-clock cost of the timers unambiguously.
#
# Output: one JSON per (Lq, Lk, sample) into $DATA_DIR containing the
# DedupDiagRecorder atexit dump.
#
# Env vars:
#   TORCH_SPYRE_CHECKOUT  path to the torch-spyre working tree (default $HOME/pr3806/torch-spyre)
#   HARNESS               path to workload_harness.py (from the existing timing patches/)
#   DATA_DIR              output directory (default $HOME/pr3806/data-diag)
#   SWEEP_SAMPLES         cold samples per point (default 3)

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness.py}
DATA=${DATA_DIR:-$WORKDIR/data-diag}
N=${SWEEP_SAMPLES:-3}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_DEDUP_DIAG=1
mkdir -p "$DATA"

# Todd's three points from the phase-2 plan.
POINTS=(
  "512 1024"   # 8 inner bodies — baseline
  "512 4096"   # 32
  "512 8192"   # 64
)

echo "=== [$(date -Is)] dedup-diag sweep starting; points=${#POINTS[@]}; N=$N ==="

for point in "${POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    LOG="$DATA/point-${Lq}x${Lk}.log"
    : > "$LOG"
    for i in $(seq 1 "$N"); do
        OUT="$DATA/dedup-${Lq}x${Lk}-run${i}.json"
        CACHE_DIR="/tmp/torchinductor_dedup_diag_${Lq}x${Lk}_r${i}"
        export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
        export SPYRE_DEDUP_DIAG_OUT="$OUT"
        rm -rf "$CACHE_DIR"
        rm -f "$OUT"

        echo "=== [$(date -Is)] Lq=$Lq Lk=$Lk sample=$i/$N ==="
        START=$(date +%s)
        set +e
        python "$HARNESS" --Lq "$Lq" --Lk "$Lk" --out /dev/null >> "$LOG" 2>&1
        RC=$?
        set -e
        END=$(date +%s)
        ELAPSED=$((END - START))
        if [ "$RC" -eq 0 ]; then
            SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
            echo "OK  Lq=$Lq Lk=$Lk sample=$i rc=0 elapsed=${ELAPSED}s json_bytes=$SIZE"
        else
            echo "FAIL Lq=$Lq Lk=$Lk sample=$i rc=$RC elapsed=${ELAPSED}s (see $LOG)"
        fi
    done
    echo "=== [$(date -Is)] point Lq=$Lq Lk=$Lk done ==="
done

echo "=== [$(date -Is)] dedup-diag sweep complete ==="
