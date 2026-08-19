#!/bin/bash
# Phase 4 — Lq extent sweep at fixed n_chunks=4.
# Tests whether compile cost is driven by graph size or by tensor extent.
#
# PR #3812's `test_hint_flash_attention_kv_chunked_prefill_8k` docstring:
#   "the same 4-chunk graph at Lq=8192 compiled for over two hours without
#    finishing, while at Lq=512 it takes well under a minute"

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness_kvchunk.py}
DATA=${DATA_DIR:-$WORKDIR/data-lq-sweep}
LQS=${LQS:-"64 128 256 512"}      # skip 1024+ unless smaller points warrant
N=${SWEEP_SAMPLES:-1}              # 1 sample per point is enough for phase 4
POINT_TAG=${POINT_TAG:-post}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA"

echo "=== [$(date -Is)] Lq sweep driver starting; Lqs=($LQS); N=$N ==="

# Fixed at n_chunks=4: kv_block=1024, Lk=4096.
kv_block=1024
lk=4096
n_chunks=$((lk / kv_block))

for lq in $LQS; do
    LOG="$DATA/point-lq${lq}.log"
    : > "$LOG"
    for i in $(seq 1 "$N"); do
        OUT="$DATA/lq${lq}-nchunks${n_chunks}-run${i}${POINT_TAG:+-$POINT_TAG}.json"
        CACHE_DIR="/tmp/torchinductor_lqsweep_lq${lq}_r${i}"
        export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
        rm -rf "$CACHE_DIR"

        echo "=== [$(date -Is)] Lq=$lq n_chunks=$n_chunks sample=$i/$N ==="
        START=$(date +%s)
        set +e
        timeout 900 python "$HARNESS" \
            --B 1 --H 8 --D 128 --Lq "$lq" --Lk "$lk" \
            --kv-block "$kv_block" \
            --h-tiles 4 --lq-tiles 0 \
            --out "$OUT" >> "$LOG" 2>&1
        RC=$?
        set -e
        END=$(date +%s)
        ELAPSED=$((END - START))
        if [ "$RC" -eq 0 ]; then
            SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
            echo "OK   Lq=$lq n_chunks=$n_chunks sample=$i rc=0 elapsed=${ELAPSED}s json_bytes=$SIZE"
        elif [ "$RC" -eq 124 ]; then
            echo "TO   Lq=$lq n_chunks=$n_chunks sample=$i rc=124 (900s timeout — expected for very large Lq)"
        else
            echo "FAIL Lq=$lq n_chunks=$n_chunks sample=$i rc=$RC elapsed=${ELAPSED}s (see $LOG)"
        fi
    done
    echo "=== [$(date -Is)] Lq=$lq done ==="
done

echo "=== [$(date -Is)] Lq sweep driver complete ==="
