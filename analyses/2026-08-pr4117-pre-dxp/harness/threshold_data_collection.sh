#!/usr/bin/env bash
# Threshold-prototype data collection for the first #4117 follow-up.
#
# Runs greedy at every shape we do NOT already have in the baseline
# greedy_compat data, so per-shape "fallback compile time" can be
# computed for any threshold from measured samples alone.
#
# Two relayout arms:
#   A: SPYRE_LX_PLANNER_RELAYOUT=1 (greedy's normal behavior)
#   B: SPYRE_LX_PLANNER_RELAYOUT=0 (cleaner solver-only fallback)
#
# 1 sample each — mechanism/threshold study, not variance study.
# The baseline final_sweep/primary already has 3-sample CP-SAT data
# at every shape for direct comparison.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/threshold_data}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"

FROZEN_SHA="3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f"
HEAD_SHA="$(git -C "$TORCH_SPYRE_REPO" rev-parse HEAD)"
if [[ "$HEAD_SHA" != "$FROZEN_SHA" ]]; then
    echo "FATAL: HEAD=$HEAD_SHA expected $FROZEN_SHA" >&2
    exit 2
fi

export TORCH_SPYRE_TIMING=1
export USE_SPYRE_CCL=0
export CO_OPTIMIZING_LX_PLANNING=0
export LX_PLANNING=1
export SENCORES=32
unset SPYRE_DUMP_COST

mkdir -p "$DATA_DIR/arm_A_relayout_on" "$DATA_DIR/arm_B_relayout_off"

# Shape list = all 15 primary shapes (flash + MLP), so we have
# per-shape greedy numbers to pair with the baseline CP-SAT ones.
FLASH_POINTS=(
    "256 1024" "512 512" "512 1024" "512 2048" "1024 1024"
    "512 4096" "2048 1024" "512 8192" "1024 8192"
)
MLP_LAYERS=(2 4 8 16 32 64)
MLP_N_IN=1024
MLP_N_HIDDEN=2048

run_one() {
    local arm_dir="$1"; shift
    local tag="$1"; shift
    local relayout="$1"; shift
    local cache="/tmp/tsc-thr-${tag}-${relayout}"
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"
    export LAYOUT_SOLVER="greedy"
    export SPYRE_LX_PLANNER_RELAYOUT="$relayout"
    local out="$arm_dir/${tag}.json"
    local cat="$arm_dir/${tag}.catalog.json"
    local log="$arm_dir/${tag}.log"

    echo "=== [$(date -Is)] $tag relayout=$relayout ==="
    local start end elapsed rc
    start=$(date +%s)
    set +e
    python3 "$HARNESS" --mode stop \
        --out "$out" --catalog "$cat" \
        --expect-solver greedy \
        "$@" >"$log" 2>&1
    rc=$?
    set -e
    end=$(date +%s)
    elapsed=$((end - start))
    if [[ $rc -eq 0 ]]; then
        echo "OK   $tag/relayout=$relayout rc=0 elapsed=${elapsed}s"
    else
        echo "FAIL $tag/relayout=$relayout rc=$rc elapsed=${elapsed}s"
    fi
}

# Arm A: relayout=1
echo "=== BEGIN arm A (relayout=1) ==="
for point in "${FLASH_POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    tag="flash-${Lq}x${Lk}"
    run_one "$DATA_DIR/arm_A_relayout_on" "$tag" 1 \
        --workload flash --Lq "$Lq" --Lk "$Lk"
done
for L in "${MLP_LAYERS[@]}"; do
    tag="mlp-L${L}-w${MLP_N_HIDDEN}"
    run_one "$DATA_DIR/arm_A_relayout_on" "$tag" 1 \
        --workload mlp --N-in "$MLP_N_IN" \
        --N-hidden "$MLP_N_HIDDEN" --layers "$L"
done

# Arm B: relayout=0
echo "=== BEGIN arm B (relayout=0) ==="
for point in "${FLASH_POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    tag="flash-${Lq}x${Lk}"
    run_one "$DATA_DIR/arm_B_relayout_off" "$tag" 0 \
        --workload flash --Lq "$Lq" --Lk "$Lk"
done
for L in "${MLP_LAYERS[@]}"; do
    tag="mlp-L${L}-w${MLP_N_HIDDEN}"
    run_one "$DATA_DIR/arm_B_relayout_off" "$tag" 0 \
        --workload mlp --N-in "$MLP_N_IN" \
        --N-hidden "$MLP_N_HIDDEN" --layers "$L"
done

echo "=== threshold data collection complete ==="
