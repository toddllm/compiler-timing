#!/usr/bin/env bash
# Solver A/B for epic #4117 — post-pilot diagnostic.
#
# Runs the same workload under LAYOUT_SOLVER=cpsat (current default)
# and LAYOUT_SOLVER=greedy (Will's faff191 baseline), preserving all
# other LX / co-optimizer / relayout / sencores knobs at their
# faff191-matching defaults on frozen SHA 3358f39.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/solver_ab}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"
export TORCH_SPYRE_TIMING=1
export USE_SPYRE_CCL=0

# Pilot's resolved knobs, made explicit (all match Will's faff191 defaults
# except layout_solver, which is the variable of interest).
export CO_OPTIMIZING_LX_PLANNING=0
export LX_PLANNING=1
export SPYRE_LX_PLANNER_RELAYOUT=1
export SENCORES=32

mkdir -p "$DATA_DIR"

run_one() {
    local shape="$1"; shift
    local solver="$1"; shift
    local Lq="$1"; shift
    local Lk="$1"; shift
    local out="$DATA_DIR/${shape}-${solver}.json"
    local cat="$DATA_DIR/${shape}-${solver}.catalog.json"
    local cache="/tmp/tsc-solver-ab-${shape}-${solver}"
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

SHAPES=("${AB_SHAPES:-flash-512x1024:512:1024}")
IFS=" " read -r -a SHAPES <<< "${AB_SHAPES:-flash-512x1024:512:1024}"

for shape_spec in "${SHAPES[@]}"; do
    IFS=":" read -r shape Lq Lk <<< "$shape_spec"
    for solver in cpsat greedy; do
        run_one "$shape" "$solver" "$Lq" "$Lk"
    done
done

echo "=== [$(date -Is)] solver A/B complete"
