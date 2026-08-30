#!/usr/bin/env bash
# End-to-end validation driver for the rebased #4139 branch.
# Runs flash 512x4096 (3 cold), flash 512x8192 (3 cold), one MLP, one SDPA
# through torch.compile with instrumentation on plan_layout, then dumps
# a JSON summary and prints per-workload aggregates.

set -euo pipefail

OUTDIR="${OUTDIR:-/tmp/valpr4139}"
HARNESS="${HARNESS:-$HOME/pr4117/compiler-timing/analyses/2026-08-pr4117-pre-dxp/harness/seed_endtoend_probe.py}"

mkdir -p "$OUTDIR"

run() {
    local name=$1
    shift
    echo "=== $name ==="
    python3 "$HARNESS" --out "$OUTDIR/$name.json" "$@"
    echo
}

run flash_4096 --workload flash --Lq 512 --Lk 4096 --samples 3
run flash_8192 --workload flash --Lq 512 --Lk 8192 --samples 3
run mlp_L96    --workload mlp    --N-in 1024 --N-hidden 4096 --layers 4
run sdpa_S512  --workload sdpa   --S 512 --D 128 --H 8 --B 1

echo "=== summary written to $OUTDIR/*.json ==="
