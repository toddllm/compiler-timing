#!/usr/bin/env bash
# Cold-compile sweep driver for the pre-DXP frontend investigation.
#
# Executes each (workload, shape) point N times serially with a fresh
# TORCHINDUCTOR_CACHE_DIR per sample. Never runs samples in parallel: the
# Spyre device is exclusive per process. Writes one JSON per sample to
# $DATA_DIR and a per-point log next to it.
#
# Requires the instrumentation patch to be applied (see
# patches/apply_instrumentation.sh).
#
# Environment overrides:
#   TORCH_SPYRE_REPO         path to editable torch-spyre with instrumentation
#   HARNESS                  path to pre_dxp_stop.py
#   DATA_DIR                 output dir (default: sibling data/sweep/)
#   SWEEP_SAMPLES            samples per point (default: 3)
#   INCLUDE_MLP              set to 1 to also run the non-flash sweep

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO to the instrumented torch-spyre repo root}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/sweep}"
: "${SWEEP_SAMPLES:=3}"
: "${INCLUDE_MLP:=1}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"
export TORCH_SPYRE_TIMING=1
mkdir -p "$DATA_DIR"

# Flash-attention (Lq, Lk) points, in order of increasing inner-body count.
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

# MLP (N_in, N_hidden, layers) points, sized so the largest is comparable
# to the largest flash graph.
MLP_POINTS=(
  "1024 2048 2"
  "1024 4096 4"
  "2048 4096 4"
  "2048 8192 8"
  "4096 8192 8"
)

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
    python3 "$HARNESS" --out "$out" "$@" >> "$LOG" 2>&1
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
echo "    flash points: ${#FLASH_POINTS[@]}   mlp points: ${#MLP_POINTS[@]}"

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
    for point in "${MLP_POINTS[@]}"; do
        read -r Nin Nh L <<< "$point"
        LOG="$DATA_DIR/mlp-${Nin}x${Nh}-L${L}.log"; : > "$LOG"
        for i in $(seq 1 "$SWEEP_SAMPLES"); do
            OUT="$DATA_DIR/mlp-${Nin}x${Nh}-L${L}-run${i}.json"
            CACHE="/tmp/tsc-sweep-mlp-${Nin}x${Nh}-L${L}-r${i}"
            run_one "mlp Nin=$Nin Nh=$Nh L=$L sample=$i/$SWEEP_SAMPLES" \
                "$OUT" "$CACHE" \
                --workload mlp --N-in "$Nin" --N-hidden "$Nh" --layers "$L"
        done
        echo "=== [$(date -Is)] mlp Nin=$Nin Nh=$Nh L=$L done"
    done
fi

echo "=== [$(date -Is)] sweep driver complete"
