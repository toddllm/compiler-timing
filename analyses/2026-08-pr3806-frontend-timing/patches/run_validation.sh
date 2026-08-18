#!/bin/bash
# Validation run for the extra timing boundaries.
#
# Preconditions:
#   - The primary sweep is not in progress. The Spyre device is exclusive
#     to a single process; running this concurrently with another
#     compile that touches Spyre will fail or hang.
#   - The checked-out torch-spyre has ``extra_timers.py`` in
#     ``torch_spyre/_inductor/`` and ``__init__.py`` calls
#     ``install_extra_timers()`` on Spyre compiles (see
#     ``extra_timers-hook.patch``).
#
# What it does:
#   - Executes ``workload_harness.py`` at (Lq=512, Lk=1024) and
#     (Lq=512, Lk=2048), 2 cold-compile samples each.
#   - Isolates each run in its own ``TORCHINDUCTOR_CACHE_DIR``.
#   - Writes JSON dumps under ``data-validation/`` so the primary
#     sweep dataset is unaffected.
#   - ``analyze_validation.py`` then decomposes
#     ``unattributed_compile_fx`` using the extra_timers events.
#
# Env: ``TORCH_SPYRE_TIMING=1`` must be set (the harness enforces this).

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness.py}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_TIMING=1

DATA=${VALIDATION_DATA_DIR:-$WORKDIR/data-validation}
mkdir -p "$DATA"

POINTS=(
  "512 1024"   # baseline
  "512 2048"   # medium (16 inner bodies)
)
N=${VALIDATION_SAMPLES:-2}

for point in "${POINTS[@]}"; do
    read -r Lq Lk <<< "$point"
    for i in $(seq 1 "$N"); do
        OUT=$DATA/${Lq}x${Lk}-run${i}.json
        CACHE=/tmp/torchinductor_valid_${Lq}x${Lk}_r${i}
        export TORCHINDUCTOR_CACHE_DIR=$CACHE
        rm -rf "$CACHE"

        echo "=== [$(date -Is)] validation: Lq=$Lq Lk=$Lk sample=$i/$N -> $OUT ==="
        START=$(date +%s)
        set +e
        python "$HARNESS" --Lq "$Lq" --Lk "$Lk" --out "$OUT" 2>&1 | tail -5
        RC=$?
        set -e
        END=$(date +%s)
        echo "  rc=$RC elapsed=$((END-START))s"
        if [ "$RC" -ne 0 ]; then
            echo "FAIL — halting"
            exit "$RC"
        fi
    done
done

echo "=== [$(date -Is)] validation runs complete: 2 points × $N samples ==="
ls -la "$DATA"/*.json
