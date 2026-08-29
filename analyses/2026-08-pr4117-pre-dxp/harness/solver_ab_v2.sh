#!/usr/bin/env bash
# Solver A/B v2 — same-tree CP-SAT vs greedy at two flash shapes with:
#   * scratchpad_plan_allocation phase timing + eligibility/placement stats
#   * OR-Tools solver stats (status, walltime, branches, conflicts,
#     workers, time limit)
#   * placed/spilled name signatures
#   * cost-model total_us plan quality metric (SPYRE_DUMP_COST=1)
#
# All other resolved config identical.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/solver_ab_v2}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"

# Everything the pilot resolved, made explicit + cost model turned on.
export TORCH_SPYRE_TIMING=1
export USE_SPYRE_CCL=0
export CO_OPTIMIZING_LX_PLANNING=0
export LX_PLANNING=1
export SPYRE_LX_PLANNER_RELAYOUT=1
export SENCORES=32
export SPYRE_DUMP_COST=1

mkdir -p "$DATA_DIR"

run_one() {
    local shape="$1"; shift
    local solver="$1"; shift
    local Lq="$1"; shift
    local Lk="$1"; shift
    local out="$DATA_DIR/${shape}-${solver}.json"
    local cat="$DATA_DIR/${shape}-${solver}.catalog.json"
    local cache="/tmp/tsc-ab2-${shape}-${solver}"
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"
    export LAYOUT_SOLVER="$solver"

    echo "=== [$(date -Is)] shape=$shape solver=$solver Lq=$Lq Lk=$Lk ==="
    local start end elapsed rc
    start=$(date +%s)
    set +e
    python3 "$HARNESS" \
        --workload flash --Lq "$Lq" --Lk "$Lk" --mode stop \
        --out "$out" --catalog "$cat" >"${out%.json}.log" 2>&1
    rc=$?
    set -e
    end=$(date +%s)
    elapsed=$((end - start))
    if [[ $rc -eq 0 ]]; then
        echo "OK   $shape/$solver rc=0 elapsed=${elapsed}s"
    else
        echo "FAIL $shape/$solver rc=$rc elapsed=${elapsed}s (see ${out%.json}.log)"
    fi
}

for shape_spec in "flash-512x1024:512:1024" "flash-512x8192:512:8192"; do
    IFS=":" read -r shape Lq Lk <<< "$shape_spec"
    for solver in cpsat greedy; do
        run_one "$shape" "$solver" "$Lq" "$Lk"
    done
done

echo "=== [$(date -Is)] solver A/B v2 complete"
