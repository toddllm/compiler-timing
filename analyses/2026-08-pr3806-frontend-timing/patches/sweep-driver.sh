#!/bin/bash
# Cold-compile sweep driver.
#
# Executes the full (Lq, Lk) × N-samples matrix serially. Never runs
# samples in parallel: the Spyre device is exclusive per process.
# Writes JSON dumps to $DATA_DIR and a per-point log to
# $DATA_DIR/point-<lq>x<lk>.log. Emits one status line per run to
# stdout so the run can be followed without tailing per-point logs.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness.py}
DATA=${DATA_DIR:-$WORKDIR/data}
N=${SWEEP_SAMPLES:-3}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA"

# (Lq, Lk) points, in order of increasing predicted inner_bodies.
POINTS=(
  "256 1024"    # 4   inner bodies
  "512 512"     # 4
  "512 1024"    # 8   baseline
  "512 2048"    # 16
  "1024 1024"   # 16
  "512 4096"    # 32
  "2048 1024"   # 32
  "512 8192"    # 64
  "1024 8192"   # 128 largest
)

echo "=== [$(date -Is)] sweep driver starting; points=${#POINTS[@]}; N=$N ==="

for point in "${POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    LOG="$DATA/point-${Lq}x${Lk}.log"
    : > "$LOG"
    for i in $(seq 1 "$N"); do
        OUT="$DATA/${Lq}x${Lk}-run${i}.json"
        CACHE_DIR="/tmp/torchinductor_sweep_${Lq}x${Lk}_r${i}"
        export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
        rm -rf "$CACHE_DIR"

        echo "=== [$(date -Is)] Lq=$Lq Lk=$Lk sample=$i/$N ==="
        START=$(date +%s)
        set +e
        python "$HARNESS" --Lq "$Lq" --Lk "$Lk" --out "$OUT" >> "$LOG" 2>&1
        RC=$?
        set -e
        END=$(date +%s)
        ELAPSED=$((END - START))
        if [ "$RC" -eq 0 ]; then
            SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
            echo "OK  Lq=$Lq Lk=$Lk sample=$i rc=0 elapsed=${ELAPSED}s json_bytes=$SIZE"
        else
            echo "FAIL Lq=$Lq Lk=$Lk sample=$i rc=$RC elapsed=${ELAPSED}s (see $LOG)"
            # On failure, log and continue to the next point so the boundary
            # of failure is recorded rather than hidden.
        fi
    done
    echo "=== [$(date -Is)] point Lq=$Lq Lk=$Lk done ==="
done

echo "=== [$(date -Is)] sweep driver complete ==="
