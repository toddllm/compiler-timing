#!/bin/bash
# H-dimension controlled sweep at fixed Lq=512, Lk=1024.
# Same cold-compile hygiene as the primary driver.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness.py}
DATA=${DATA_DIR:-$WORKDIR/data-h-sweep}
N=${SWEEP_SAMPLES:-3}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA"

H_VALUES=(16 32)
Lq=512
Lk=1024

echo "=== [$(date -Is)] H-sweep driver starting; H_values=${H_VALUES[*]}; N=$N ==="

for H in "${H_VALUES[@]}"; do
    LOG="$DATA/point-h${H}-${Lq}x${Lk}.log"
    : > "$LOG"
    for i in $(seq 1 "$N"); do
        OUT="$DATA/h${H}-${Lq}x${Lk}-run${i}.json"
        CACHE_DIR="/tmp/torchinductor_sweep_h${H}_${Lq}x${Lk}_r${i}"
        export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
        rm -rf "$CACHE_DIR"

        echo "=== [$(date -Is)] H=$H Lq=$Lq Lk=$Lk sample=$i/$N ==="
        START=$(date +%s)
        set +e
        python "$HARNESS" --H "$H" --Lq "$Lq" --Lk "$Lk" --out "$OUT" >> "$LOG" 2>&1
        RC=$?
        set -e
        END=$(date +%s)
        ELAPSED=$((END - START))
        if [ "$RC" -eq 0 ]; then
            SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
            echo "OK  H=$H Lq=$Lq Lk=$Lk sample=$i rc=0 elapsed=${ELAPSED}s json_bytes=$SIZE"
        else
            echo "FAIL H=$H Lq=$Lq Lk=$Lk sample=$i rc=$RC elapsed=${ELAPSED}s (see $LOG)"
        fi
    done
    echo "=== [$(date -Is)] H=$H done ==="
done

echo "=== [$(date -Is)] H-sweep driver complete ==="
