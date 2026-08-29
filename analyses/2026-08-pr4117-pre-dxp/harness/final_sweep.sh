#!/usr/bin/env bash
# Final #4117 sweep: primary CP-SAT + historical greedy compatibility.
#
# Primary (LAYOUT_SOLVER=cpsat):
#   9 flash shapes + 6 layer-scaled MLP shapes × 3 cold samples = 45 runs.
# Historical compatibility (LAYOUT_SOLVER=greedy):
#   flash 512x1024, 512x4096, 512x8192 × 3 cold samples = 9 runs.
#
# Serial. Fresh TORCHINDUCTOR_CACHE_DIR per sample. Fresh process per
# sample. Every sample is asserted to match its arm via --expect-solver
# and refuses to run if the cost model is on.
#
# Env overrides (must all be default for a valid baseline; the driver
# enforces them):
#   USE_SPYRE_CCL=0
#   CO_OPTIMIZING_LX_PLANNING=0
#   LX_PLANNING=1
#   SPYRE_LX_PLANNER_RELAYOUT=1
#   SENCORES=32
#   SPYRE_DUMP_COST is UNSET (cost model off for the timing baseline).

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO}"
: "${HARNESS:=${HERE}/pre_dxp_stop.py}"
: "${DATA_DIR:=${HERE}/../data/final_sweep}"

cd "$TORCH_SPYRE_REPO"
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi
export PATH="${HOME}/.local/bin:${PATH}"

# Assert we are at the frozen SHA. The instrumentation applier already
# checks this, but a driver-side check catches accidental HEAD moves
# between apply and sweep.
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
export SPYRE_LX_PLANNER_RELAYOUT=1
export SENCORES=32
# Explicitly clear cost-model env — the harness also asserts config off.
unset SPYRE_DUMP_COST

mkdir -p "$DATA_DIR/primary" "$DATA_DIR/greedy_compat" "$DATA_DIR/invalid"

# Flash-attention (Lq, Lk) points, in order of increasing inner-body count.
FLASH_POINTS=(
  "256 1024"    # 4   inner bodies
  "512 512"     # 4
  "512 1024"    # 8
  "512 2048"    # 16
  "1024 1024"   # 16
  "512 4096"    # 32
  "2048 1024"   # 32
  "512 8192"    # 64
  "1024 8192"   # 128
)

# Layer-scaled MLP (fixed moderate width, sweep layers).
MLP_N_IN=1024
MLP_N_HIDDEN=2048
MLP_LAYERS=(2 4 8 16 32 64)

# Greedy compatibility set — flash only, aligned with PR #3806 / Will's
# Lq=512 axis. NOTE: 512x8192 not 1024x8192, per the sweep instructions.
GREEDY_COMPAT=(
  "512 1024"
  "512 4096"
  "512 8192"
)

SAMPLES="${SWEEP_SAMPLES:-3}"

# ---- one sample -----------------------------------------------------------
run_one() {
    local out_dir="$1"; shift
    local tag="$1"; shift
    local solver="$1"; shift
    local cache_prefix="$1"; shift
    local i="$1"; shift
    local sample_out="$out_dir/${tag}-run${i}.json"
    local sample_cat="$out_dir/${tag}-run${i}.catalog.json"
    local sample_log="$out_dir/${tag}-run${i}.log"
    local cache="/tmp/${cache_prefix}-${tag}-r${i}"
    rm -rf "$cache"
    export TORCHINDUCTOR_CACHE_DIR="$cache"
    export LAYOUT_SOLVER="$solver"

    echo "=== [$(date -Is)] $tag sample=$i/$SAMPLES solver=$solver ==="
    local start end elapsed rc
    start=$(date +%s)
    set +e
    python3 "$HARNESS" --mode stop \
        --out "$sample_out" --catalog "$sample_cat" \
        --expect-solver "$solver" \
        "$@" >"$sample_log" 2>&1
    rc=$?
    set -e
    end=$(date +%s)
    elapsed=$((end - start))
    if [[ $rc -eq 0 ]]; then
        echo "OK   $tag/$solver sample=$i rc=0 elapsed=${elapsed}s"
    else
        echo "FAIL $tag/$solver sample=$i rc=$rc elapsed=${elapsed}s (see $sample_log)"
        # Move failed sample to invalid/
        mv "$sample_out" "$DATA_DIR/invalid/${tag}-${solver}-run${i}.json" 2>/dev/null || true
        mv "$sample_cat" "$DATA_DIR/invalid/${tag}-${solver}-run${i}.catalog.json" 2>/dev/null || true
        mv "$sample_log" "$DATA_DIR/invalid/${tag}-${solver}-run${i}.log" 2>/dev/null || true
    fi
}

# ---- primary sweep --------------------------------------------------------
echo "=== [$(date -Is)] BEGIN primary CP-SAT sweep (9 flash + 6 MLP × $SAMPLES samples)"

for point in "${FLASH_POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    tag="flash-${Lq}x${Lk}"
    for i in $(seq 1 "$SAMPLES"); do
        run_one "$DATA_DIR/primary" "$tag" cpsat "cache-primary-flash" "$i" \
            --workload flash --Lq "$Lq" --Lk "$Lk"
    done
done

for L in "${MLP_LAYERS[@]}"; do
    tag="mlp-L${L}-w${MLP_N_HIDDEN}"
    for i in $(seq 1 "$SAMPLES"); do
        run_one "$DATA_DIR/primary" "$tag" cpsat "cache-primary-mlp" "$i" \
            --workload mlp --N-in "$MLP_N_IN" \
            --N-hidden "$MLP_N_HIDDEN" --layers "$L"
    done
done

echo "=== [$(date -Is)] primary CP-SAT sweep complete"

# ---- greedy compat arm ----------------------------------------------------
echo "=== [$(date -Is)] BEGIN greedy compatibility arm (flash only, 3 shapes)"

for point in "${GREEDY_COMPAT[@]}"; do
    read -r Lq Lk <<< "$point"
    tag="flash-${Lq}x${Lk}"
    for i in $(seq 1 "$SAMPLES"); do
        run_one "$DATA_DIR/greedy_compat" "$tag" greedy "cache-greedy" "$i" \
            --workload flash --Lq "$Lq" --Lk "$Lk"
    done
done

echo "=== [$(date -Is)] greedy compatibility complete"
echo "=== [$(date -Is)] FINAL SWEEP COMPLETE"
