#!/bin/bash
# Workload family B sweep driver — KV-chunked FlashAttention from PR #3812.
# Same cold-compile hygiene as our primary sweep-driver.sh.
#
# Runs the recipe from PR #3812's test_hint_flash_attention_kv_chunked_* tests:
#   B=1 H=8 Lq=256 D=128 Lk=4096  with kv_block ∈ {2048, 1024, 512, 256, 128}
# yielding n_chunks ∈ {2, 4, 8, 16, 32}.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness_kvchunk.py}
DATA=${DATA_DIR:-$WORKDIR/data-kvchunk}
POINTS=${POINTS:-"2048 1024 512 256"}  # kv_block values; user picks samples per point via N
N=${SWEEP_SAMPLES:-3}
LABEL=${LABEL:-prefix}                 # "prefix" for post-fix, "prefix" or whatever tag we choose
POINT_TAG=${POINT_TAG:-}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA"

echo "=== [$(date -Is)] KV-chunk sweep driver starting; kv_blocks=($POINTS); N=$N ==="

for kv in $POINTS; do
    lk=4096
    n_chunks=$((lk / kv))
    LOG="$DATA/point-kv${kv}.log"
    : > "$LOG"
    for i in $(seq 1 "$N"); do
        OUT="$DATA/kv${kv}-nchunks${n_chunks}-run${i}${POINT_TAG:+-$POINT_TAG}.json"
        CACHE_DIR="/tmp/torchinductor_kvchunk_kv${kv}_r${i}${POINT_TAG:+_$POINT_TAG}"
        export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
        rm -rf "$CACHE_DIR"

        echo "=== [$(date -Is)] kv_block=$kv (n_chunks=$n_chunks) sample=$i/$N ==="
        START=$(date +%s)
        set +e
        python "$HARNESS" \
            --B 1 --H 8 --D 128 --Lq 256 --Lk 4096 \
            --kv-block "$kv" \
            --h-tiles 4 --lq-tiles 0 \
            --out "$OUT" >> "$LOG" 2>&1
        RC=$?
        set -e
        END=$(date +%s)
        ELAPSED=$((END - START))
        if [ "$RC" -eq 0 ]; then
            SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
            echo "OK   kv=$kv n_chunks=$n_chunks sample=$i rc=0 elapsed=${ELAPSED}s json_bytes=$SIZE"
        else
            echo "FAIL kv=$kv n_chunks=$n_chunks sample=$i rc=$RC elapsed=${ELAPSED}s (see $LOG)"
        fi
    done
    echo "=== [$(date -Is)] kv_block=$kv done ==="
done

echo "=== [$(date -Is)] KV-chunk sweep driver complete ==="
