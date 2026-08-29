#!/usr/bin/env bash
# Cold-compile sweep driver for the pre-DXP frontend investigation.
#
# Runs each (workload, shape) point N times serially, fresh
# TORCHINDUCTOR_CACHE_DIR per sample. The Spyre device is exclusive
# per process, so samples MUST NOT run in parallel.
#
# Writes one JSON per sample to $DATA_DIR and a per-point log.
#
# Requires the instrumentation patch to be applied (see
# patches/apply_instrumentation.sh) against the frozen SHA.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO to the instrumented torch-spyre repo root}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/sweep}"
: "${SWEEP_SAMPLES:=3}"
: "${INCLUDE_MLP:=1}"
: "${MODE:=stop}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA_DIR"

# Flash-attention (Lq, Lk) points, in order of increasing inner-body count.
# Same as the PR #3806 study so results are directly comparable.
FLASH_POINTS=(
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

# Layer-scaled MLP: hold width moderate, sweep layer count.
# Width chosen so the biggest layer count still fits on-device.
# N_IN, N_HIDDEN are fixed; layers is the independent axis.
MLP_N_IN=1024
MLP_N_HIDDEN=2048
MLP_LAYERS=(2 4 8 16 32 64)

run_one() {
    local tag="$1"; shift
    local out="$1"; shift
    local cache="$1"; shift
    local start end elapsed rc size
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"

    echo "=== [$(date -Is)] $tag ==="
    start=$(date +%s)
    set +e
    python3 "$HARNESS" --mode "$MODE" --out "$out" "$@" >> "$LOG" 2>&1
    rc=$?
    set -e
    end=$(date +%s)
    elapsed=$((end - start))
    if [[ $rc -eq 0 ]]; then
        size=$(stat -c %s "$out" 2>/dev/null || stat -f %z "$out" 2>/dev/null || echo 0)
        echo "OK   $tag rc=0 elapsed=${elapsed}s json_bytes=$size"
    else
        echo "FAIL $tag rc=$rc elapsed=${elapsed}s (see $LOG)"
    fi
}

echo "=== [$(date -Is)] sweep driver starting"
echo "    TORCH_SPYRE_REPO=$TORCH_SPYRE_REPO"
echo "    HARNESS=$HARNESS"
echo "    DATA_DIR=$DATA_DIR"
echo "    SWEEP_SAMPLES=$SWEEP_SAMPLES"
echo "    INCLUDE_MLP=$INCLUDE_MLP"
echo "    MODE=$MODE"
echo "    flash points: ${#FLASH_POINTS[@]}   mlp layer points: ${#MLP_LAYERS[@]}"

for point in "${FLASH_POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    LOG="$DATA_DIR/flash-${Lq}x${Lk}.log"; : > "$LOG"
    for i in $(seq 1 "$SWEEP_SAMPLES"); do
        OUT="$DATA_DIR/flash-${Lq}x${Lk}-run${i}.json"
        CACHE="/tmp/tsc-sweep-flash-${Lq}x${Lk}-r${i}"
        run_one "flash Lq=$Lq Lk=$Lk sample=$i/$SWEEP_SAMPLES" \
            "$OUT" "$CACHE" \
            --workload flash --Lq "$Lq" --Lk "$Lk"
    done
    echo "=== [$(date -Is)] flash Lq=$Lq Lk=$Lk done"
done

if [[ "$INCLUDE_MLP" == "1" ]]; then
    for L in "${MLP_LAYERS[@]}"; do
        LOG="$DATA_DIR/mlp-L${L}-w${MLP_N_HIDDEN}.log"; : > "$LOG"
        for i in $(seq 1 "$SWEEP_SAMPLES"); do
            OUT="$DATA_DIR/mlp-L${L}-w${MLP_N_HIDDEN}-run${i}.json"
            CACHE="/tmp/tsc-sweep-mlp-L${L}-w${MLP_N_HIDDEN}-r${i}"
            run_one "mlp L=$L width=$MLP_N_HIDDEN sample=$i/$SWEEP_SAMPLES" \
                "$OUT" "$CACHE" \
                --workload mlp --N-in "$MLP_N_IN" \
                --N-hidden "$MLP_N_HIDDEN" --layers "$L"
        done
        echo "=== [$(date -Is)] mlp L=$L done"
    done
fi

echo "=== [$(date -Is)] sweep driver complete"
