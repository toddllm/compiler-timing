#!/usr/bin/env bash
# A/B fresh-process wall-time comparison for lazy OR-Tools.
# Run 5 fresh-process samples for each arm. Take the median.

set -u

if [ "${1:-}" = "" ]; then
    echo "usage: $0 <arm-label>" >&2
    exit 2
fi
ARM="$1"
N="${SAMPLES:-5}"

OUTDIR="/tmp/lazy_ortools_ab/${ARM}"
mkdir -p "$OUTDIR"

cd ~/pr4117/torch-spyre
source .venv/bin/activate

for i in $(seq 0 $((N-1))); do
    echo "=== arm=${ARM} sample=${i} ===" >&2
    rm -rf /tmp/fixed_startup_probe_cache
    # Purposefully NOT priming any inductor cache -- we want fresh state.
    python3 ~/pr4117/compiler-timing/analyses/2026-08-pr4117-pre-dxp/harness/fixed_startup_probe.py 2>/dev/null | tee "${OUTDIR}/sample_${i}.txt"
    # Also run the import-chain probe on the same fresh process
    python3 ~/pr4117/compiler-timing/analyses/2026-08-pr4117-pre-dxp/harness/ortools_import_chain_probe.py \
        --out "${OUTDIR}/import_chain_${i}.json" > "${OUTDIR}/import_chain_${i}.log" 2>&1
done

echo "=== summary arm=${ARM} ===" >&2
python3 <<PY
import re
import os
import statistics

outdir = "${OUTDIR}"
walls = []
first_calls = []
second_calls = []
for i in range(${N}):
    p = os.path.join(outdir, f"sample_{i}.txt")
    text = open(p).read()
    m = re.search(r"total wall since script start:\s+([\d.]+)\s+s", text)
    if m: walls.append(float(m.group(1)))
    m = re.search(r"first_call_wall:\s+([\d.]+)\s+s", text)
    if m: first_calls.append(float(m.group(1)))
    m = re.search(r"second_call_wall:\s+([\d.]+)\s+ms", text)
    if m: second_calls.append(float(m.group(1)))
print(f"arm={'${ARM}'}")
print(f"  total wall  (n={len(walls)}):  median {statistics.median(walls):.3f} s  min {min(walls):.3f}  max {max(walls):.3f}")
print(f"  first_call  (n={len(first_calls)}):  median {statistics.median(first_calls):.3f} s  min {min(first_calls):.3f}  max {max(first_calls):.3f}")
print(f"  second_call (n={len(second_calls)}):  median {statistics.median(second_calls):.2f} ms  min {min(second_calls):.2f}  max {max(second_calls):.2f}")
PY
