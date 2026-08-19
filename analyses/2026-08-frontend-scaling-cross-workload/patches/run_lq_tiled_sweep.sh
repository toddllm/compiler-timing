#!/bin/bash
# Phase 4 continued — Lq extent sweep with Lq WSR tiling ENABLED.
# Reproduces PR #3812's prefill_8k geometry: h_tiles=4, lq_tiles=2, at fixed
# n_chunks=4 but varying Lq.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness_kvchunk.py}
DATA=${DATA_DIR:-$WORKDIR/data-lq-tiled-sweep}
LQS=${LQS:-"256 512 1024 2048"}
N=${SWEEP_SAMPLES:-1}
POINT_TAG=${POINT_TAG:-lqtiled}
LQ_TILES=${LQ_TILES:-2}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA"

kv_block=1024
lk=4096
n_chunks=$((lk / kv_block))

echo "=== [$(date -Is)] Lq tiled sweep starting; lq_tiles=$LQ_TILES ==="

for lq in $LQS; do
    LOG="$DATA/point-lq${lq}-t${LQ_TILES}.log"
    : > "$LOG"
    for i in $(seq 1 "$N"); do
        OUT="$DATA/lq${lq}-t${LQ_TILES}-nchunks${n_chunks}-run${i}-${POINT_TAG}.json"
        CACHE_DIR="/tmp/torchinductor_lqtiled_lq${lq}_t${LQ_TILES}_r${i}"
        export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
        rm -rf "$CACHE_DIR"

        echo "=== [$(date -Is)] Lq=$lq lq_tiles=$LQ_TILES n_chunks=$n_chunks sample=$i/$N ==="
        START=$(date +%s)
        set +e
        timeout 1800 python "$HARNESS" \
            --B 1 --H 8 --D 128 --Lq "$lq" --Lk "$lk" \
            --kv-block "$kv_block" \
            --h-tiles 4 --lq-tiles "$LQ_TILES" \
            --out "$OUT" >> "$LOG" 2>&1
        RC=$?
        set -e
        END=$(date +%s)
        ELAPSED=$((END - START))
        if [ "$RC" -eq 0 ]; then
            SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
            echo "OK   Lq=$lq lq_tiles=$LQ_TILES sample=$i rc=0 elapsed=${ELAPSED}s json_bytes=$SIZE"
        elif [ "$RC" -eq 124 ]; then
            echo "TO   Lq=$lq lq_tiles=$LQ_TILES sample=$i rc=124 (1800s timeout — extent-driven blowup?)"
        else
            echo "FAIL Lq=$lq lq_tiles=$LQ_TILES sample=$i rc=$RC elapsed=${ELAPSED}s (see $LOG)"
        fi
    done
    echo "=== [$(date -Is)] Lq=$lq lq_tiles=$LQ_TILES done ==="
done

echo "=== [$(date -Is)] Lq tiled sweep driver complete ==="
