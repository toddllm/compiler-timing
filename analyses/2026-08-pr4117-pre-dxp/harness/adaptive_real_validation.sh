#!/usr/bin/env bash
# REAL adaptive-solver validation for the #4117 first-follow-up draft PR.
#
# Runs with configured LAYOUT_SOLVER=cpsat, threshold enabled via the new
# torch-spyre config knob (ADAPTIVE_SOLVER_THRESHOLD_OPS env). At each shape
# above threshold the actual production path swaps in the greedy fallback
# allocator with LX relayout disabled at the instance level; the timing patch
# records the chosen allocator/solver class so downstream analysis knows
# which arm ran. Baseline arm keeps threshold=None (existing CP-SAT-only
# behavior) so both arms use the same instrumented tree.
#
# 4 flash points x 3 cold samples x 2 arms = 24 runs.
#
# Requires the pod's torch-spyre tree already patched with the draft change:
#   torch_spyre/_inductor/config.py     — new adaptive_solver_threshold_ops
#   torch_spyre/_inductor/scratchpad/allocator.py — new enable_lx_relayout
#                                          + _adaptive_solver_fallback_allocator
# and the timing patch patches/extra_timers.py has placed_signature_with_address.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/adaptive_real_validation}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"

# The frozen study SHA is 3358f39, but this validation runs against the
# adaptive-solver draft applied on top. No SHA gate here — the harness knows
# the tree is intentionally patched.

export TORCH_SPYRE_TIMING=1
export USE_SPYRE_CCL=0
export CO_OPTIMIZING_LX_PLANNING=0
export LX_PLANNING=1
export SENCORES=32
unset SPYRE_DUMP_COST
export LAYOUT_SOLVER=cpsat

# Shapes chosen so len(graph.operations) spans the crossover region:
#   flash-1024x1024 -> ~516 ops
#   flash-2048x1024 -> ~1028 ops
#   flash-512x8192  -> ~2052 ops
#   flash-1024x8192 -> ~4100 ops
FLASH_POINTS=(
    "1024 1024"
    "2048 1024"
    "512 8192"
    "1024 8192"
)

# Threshold chosen so ALL four points fall above threshold and use the
# greedy fallback. flash-1024x1024 has ~516 ops so threshold=500 puts it
# just above. Using 500 also confirms the smallest-switched-point behavior.
THRESHOLD_OPS=500

mkdir -p "$DATA_DIR/baseline_cpsat" "$DATA_DIR/adaptive_greedy"

run_one() {
    local arm_dir="$1"; shift
    local tag="$1"; shift
    local threshold="$1"; shift
    local sample="$1"; shift
    local cache="/tmp/tsc-adaptive-${tag}-${threshold}-s${sample}"
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"
    if [[ "$threshold" == "off" ]]; then
        unset ADAPTIVE_SOLVER_THRESHOLD_OPS
    else
        export ADAPTIVE_SOLVER_THRESHOLD_OPS="$threshold"
    fi
    local out="$arm_dir/${tag}-run${sample}.json"
    local cat="$arm_dir/${tag}-run${sample}.catalog.json"
    local log="$arm_dir/${tag}-run${sample}.log"

    echo "=== [$(date -Is)] $tag threshold=$threshold sample=$sample ==="
    local start end elapsed rc
    start=$(date +%s)
    set +e
    python3 "$HARNESS" --mode stop \
        --out "$out" --catalog "$cat" \
        --expect-solver cpsat \
        "$@" >"$log" 2>&1
    rc=$?
    set -e
    end=$(date +%s)
    elapsed=$((end - start))
    if [[ $rc -eq 0 ]]; then
        echo "OK   $tag/threshold=$threshold/s${sample} rc=0 elapsed=${elapsed}s"
    else
        echo "FAIL $tag/threshold=$threshold/s${sample} rc=$rc elapsed=${elapsed}s"
    fi
}

echo "=== BEGIN baseline_cpsat (adaptive OFF) ==="
for point in "${FLASH_POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    tag="flash-${Lq}x${Lk}"
    for sample in 1 2 3; do
        run_one "$DATA_DIR/baseline_cpsat" "$tag" off "$sample" \
            --workload flash --Lq "$Lq" --Lk "$Lk"
    done
done

echo "=== BEGIN adaptive_greedy (adaptive ON, threshold=${THRESHOLD_OPS}) ==="
for point in "${FLASH_POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    tag="flash-${Lq}x${Lk}"
    for sample in 1 2 3; do
        run_one "$DATA_DIR/adaptive_greedy" "$tag" "$THRESHOLD_OPS" "$sample" \
            --workload flash --Lq "$Lq" --Lk "$Lk"
    done
done

echo "=== adaptive real validation complete ==="
