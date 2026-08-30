#!/usr/bin/env bash
# Held-out workload validation for the #4139 predictor study.
#
# Structural predictor was chosen using only flash + MLP data. Here
# we run three real inference primitives whose graph structure is
# different from both:
#   sdpa               — F.scaled_dot_product_attention (fused attn)
#   rms_norm           — reduction + pointwise, no matmul
#   transformer_block  — attention + MLP + norm combined
#
# For each: measure BOTH cpsat and greedy under RELAYOUT=0 (same
# planner-buffer universe), record structural metrics + greedy work
# counters + CP-SAT model geometry. Downstream analysis then reports
# actual solver-time winner vs the predictor's prediction.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/held_out_validation}"

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

mkdir -p "$DATA_DIR"

run_one() {
    local tag="$1"; shift
    local solver="$1"; shift
    local cache="/tmp/tsc-heldout-${tag}-${solver}"
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

echo "=== BEGIN held-out (sdpa) ==="
for spec in "B1_H8_S512_D128" "B1_H8_S1024_D128" "B1_H8_S2048_D128"; do
    IFS="_" read -r B_str H_str S_str D_str <<< "$spec"
    B="${B_str#B}"; H="${H_str#H}"; S="${S_str#S}"; D="${D_str#D}"
    tag="sdpa-B${B}H${H}S${S}D${D}"
    for solver in cpsat greedy; do
        run_one "$tag" "$solver" \
            --workload sdpa --B "$B" --H "$H" --S "$S" --D "$D"
    done
done

echo "=== BEGIN held-out (rms_norm) ==="
for spec in "D1024_T512" "D2048_T1024" "D4096_T2048"; do
    IFS="_" read -r D_str T_str <<< "$spec"
    D="${D_str#D}"; T="${T_str#T}"
    tag="rmsnorm-D${D}T${T}"
    for solver in cpsat greedy; do
        run_one "$tag" "$solver" \
            --workload rms_norm --rms-D "$D" --rms-T "$T"
    done
done

echo "=== BEGIN held-out (transformer_block) ==="
for spec in "S512_E1024" "S1024_E1024" "S512_E2048"; do
    IFS="_" read -r S_str E_str <<< "$spec"
    S="${S_str#S}"; E="${E_str#E}"
    tag="tblock-S${S}E${E}"
    for solver in cpsat greedy; do
        run_one "$tag" "$solver" \
            --workload transformer_block --seq-len "$S" --emb-dim "$E"
    done
done

echo "=== held-out validation complete ==="
