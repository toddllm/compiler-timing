#!/usr/bin/env bash
# Additional inference-workload coverage for the #4117 draft PR.
#
# Runs the adaptive-solver draft policy on MLP graphs at layer counts
# where len(graph.operations) crosses the threshold. MLP has a very
# different graph structure from flash (dense matmul stack, no
# tiling loop), so this exercises the policy on a second shape family
# without adding entirely new workload code.
#
# Layer counts chosen so:
#   L=128 -> ~384 ops  (BELOW threshold 500; should keep CP-SAT)
#   L=192 -> ~576 ops  (just ABOVE threshold; smallest switched MLP)
#   L=384 -> ~1152 ops (comfortably ABOVE threshold)
#
# The L=128 point is important — it verifies the "below threshold =
# unchanged" arm on MLP, not just flash.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/adaptive_mlp_coverage}"

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
export SENCORES=32
unset SPYRE_DUMP_COST
export LAYOUT_SOLVER=cpsat

MLP_LAYERS=(128 192 384)
MLP_N_IN=1024
MLP_N_HIDDEN=2048
THRESHOLD_OPS=500

mkdir -p "$DATA_DIR/baseline_cpsat" "$DATA_DIR/adaptive_greedy"

run_one() {
    local arm_dir="$1"; shift
    local tag="$1"; shift
    local threshold="$1"; shift
    local sample="$1"; shift
    local cache="/tmp/tsc-mlp-${tag}-${threshold}-s${sample}"
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
for L in "${MLP_LAYERS[@]}"; do
    tag="mlp-L${L}-w${MLP_N_HIDDEN}"
    for sample in 1 2 3; do
        run_one "$DATA_DIR/baseline_cpsat" "$tag" off "$sample" \
            --workload mlp --N-in "$MLP_N_IN" \
            --N-hidden "$MLP_N_HIDDEN" --layers "$L"
    done
done

echo "=== BEGIN adaptive_greedy (adaptive ON, threshold=${THRESHOLD_OPS}) ==="
for L in "${MLP_LAYERS[@]}"; do
    tag="mlp-L${L}-w${MLP_N_HIDDEN}"
    for sample in 1 2 3; do
        run_one "$DATA_DIR/adaptive_greedy" "$tag" "$THRESHOLD_OPS" "$sample" \
            --workload mlp --N-in "$MLP_N_IN" \
            --N-hidden "$MLP_N_HIDDEN" --layers "$L"
    done
done

echo "=== adaptive mlp coverage complete ==="
