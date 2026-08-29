#!/usr/bin/env bash
# CP-SAT investigation for the first #4117 follow-up.
#
# Runs a controlled A/B with SPYRE_LX_PLANNER_RELAYOUT=0, so cpsat and
# greedy see the SAME planner-buffer input universe. Also captures
# the CP-SAT phase decomposition + model-size metrics + per-Solve()
# OR-Tools stats.
#
# Shapes:
#   flash 512x1024, 512x2048, 512x4096, 512x8192.
# Arms:
#   cpsat, greedy.
# 1 sample each; the objective is mechanism attribution, not variance.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/cpsat_investigation}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"

# Confirm frozen SHA.
FROZEN_SHA="3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f"
HEAD_SHA="$(git -C "$TORCH_SPYRE_REPO" rev-parse HEAD)"
if [[ "$HEAD_SHA" != "$FROZEN_SHA" ]]; then
    echo "FATAL: TORCH_SPYRE_REPO HEAD=$HEAD_SHA, expected $FROZEN_SHA" >&2
    exit 2
fi

export TORCH_SPYRE_TIMING=1
export USE_SPYRE_CCL=0
export CO_OPTIMIZING_LX_PLANNING=0
export LX_PLANNING=1
export SPYRE_LX_PLANNER_RELAYOUT=0     # <-- key difference vs the main sweep
export SENCORES=32
unset SPYRE_DUMP_COST

mkdir -p "$DATA_DIR"

run_one() {
    local shape="$1"; shift
    local solver="$1"; shift
    local Lq="$1"; shift
    local Lk="$1"; shift
    local out="$DATA_DIR/${shape}-${solver}.json"
    local cat="$DATA_DIR/${shape}-${solver}.catalog.json"
    local log="$DATA_DIR/${shape}-${solver}.log"
    local cache="/tmp/tsc-cpsat-inv-${shape}-${solver}"
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"
    export LAYOUT_SOLVER="$solver"

    echo "=== [$(date -Is)] $shape/$solver Lq=$Lq Lk=$Lk (RELAYOUT=0) ==="
    local start end elapsed rc
    start=$(date +%s)
    set +e
    python3 "$HARNESS" --mode stop \
        --workload flash --Lq "$Lq" --Lk "$Lk" \
        --expect-solver "$solver" \
        --out "$out" --catalog "$cat" >"$log" 2>&1
    rc=$?
    set -e
    end=$(date +%s)
    elapsed=$((end - start))
    if [[ $rc -eq 0 ]]; then
        echo "OK   $shape/$solver rc=0 elapsed=${elapsed}s"
    else
        echo "FAIL $shape/$solver rc=$rc elapsed=${elapsed}s (see $log)"
    fi
}

for shape_spec in \
    "flash-512x1024:512:1024" \
    "flash-512x2048:512:2048" \
    "flash-512x4096:512:4096" \
    "flash-512x8192:512:8192"; do
    IFS=":" read -r shape Lq Lk <<< "$shape_spec"
    for solver in cpsat greedy; do
        run_one "$shape" "$solver" "$Lq" "$Lk"
    done
done

echo "=== [$(date -Is)] CP-SAT investigation complete"
