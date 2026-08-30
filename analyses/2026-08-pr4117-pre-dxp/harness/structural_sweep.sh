#!/usr/bin/env bash
# Structural + greedy-work sweep for the #4139 predictor-discovery study.
#
# Runs BOTH cpsat and greedy at the same shapes under
# SPYRE_LX_PLANNER_RELAYOUT=0 so the two solvers see the identical
# planner-buffer universe. Structural metrics are recorded once per
# run (they're deterministic, so 1 sample is enough); greedy internal
# work counters and CP-SAT model geometry are also recorded per run.
#
# Shapes span both families where we already know the sign of the
# solver-cost difference:
#   Flash:  512x1024 / 2048 / 4096 / 8192  (greedy wins big at scale)
#   MLP:    L128 / L192 / L384             (CP-SAT wins on the two
#                                          switched points)
# Plus a couple intermediates to make the crossover visible.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/structural_sweep}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"

export TORCH_SPYRE_TIMING=1
export USE_SPYRE_CCL=0
export CO_OPTIMIZING_LX_PLANNING=0
export LX_PLANNING=1
export SPYRE_LX_PLANNER_RELAYOUT=0
export SENCORES=32
unset SPYRE_DUMP_COST
unset ADAPTIVE_SOLVER_THRESHOLD_OPS

FLASH_POINTS=(
    "512 1024"
    "512 2048"
    "512 4096"
    "512 8192"
)
# One intermediate MLP point (L=96) added for crossover visibility.
MLP_LAYERS=(96 128 192 384)
MLP_N_IN=1024
MLP_N_HIDDEN=2048

mkdir -p "$DATA_DIR"

run_one() {
    local tag="$1"; shift
    local solver="$1"; shift
    local cache="/tmp/tsc-struct-${tag}-${solver}"
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"
    export LAYOUT_SOLVER="$solver"
    local out="$DATA_DIR/${tag}-${solver}.json"
    local cat="$DATA_DIR/${tag}-${solver}.catalog.json"
    local log="$DATA_DIR/${tag}-${solver}.log"

    echo "=== [$(date -Is)] $tag / $solver ==="
    local start end elapsed rc
    start=$(date +%s)
    set +e
    python3 "$HARNESS" --mode stop \
        --out "$out" --catalog "$cat" \
        --expect-solver "$solver" \
        "$@" >"$log" 2>&1
    rc=$?
    set -e
    end=$(date +%s)
    elapsed=$((end - start))
    if [[ $rc -eq 0 ]]; then
        echo "OK   $tag/$solver rc=0 elapsed=${elapsed}s"
    else
        echo "FAIL $tag/$solver rc=$rc elapsed=${elapsed}s"
    fi
}

echo "=== BEGIN structural sweep (flash) ==="
for point in "${FLASH_POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    tag="flash-${Lq}x${Lk}"
    for solver in cpsat greedy; do
        run_one "$tag" "$solver" \
            --workload flash --Lq "$Lq" --Lk "$Lk"
    done
done

echo "=== BEGIN structural sweep (mlp) ==="
for L in "${MLP_LAYERS[@]}"; do
    tag="mlp-L${L}-w${MLP_N_HIDDEN}"
    for solver in cpsat greedy; do
        run_one "$tag" "$solver" \
            --workload mlp --N-in "$MLP_N_IN" \
            --N-hidden "$MLP_N_HIDDEN" --layers "$L"
    done
done

echo "=== structural sweep complete ==="
