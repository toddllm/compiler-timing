#!/bin/bash
# Correctness runs for H=16 and H=32 at Lq=512, Lk=1024.
# Uses --compare-cpu which runs the CPU reference OUTSIDE the timed region.
# Runs separately from the timed sweep to avoid perturbing timing.

set +e
source /etc/bashrc 2>/dev/null || true
set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
WORKDIR=${WORKDIR:-$HOME/pr3806}
HARNESS=${HARNESS:-$WORKDIR/workload_harness.py}
OUT=${OUT:-$WORKDIR/h-correctness}

cd "$CHECKOUT"
source .venv/bin/activate
export PATH=$HOME/.local/bin:$PATH
export TORCH_SPYRE_TIMING=1
mkdir -p "$OUT"

echo "=== [$(date -Is)] H correctness starting ==="
for H in 16 32; do
    CACHE_DIR="/tmp/torchinductor_h${H}_correctness"
    rm -rf "$CACHE_DIR"
    export TORCHINDUCTOR_CACHE_DIR="$CACHE_DIR"
    RESULT="$OUT/h${H}-correctness.json"
    LOG="$OUT/h${H}-correctness.log"
    echo "=== [$(date -Is)] H=$H correctness ===" | tee -a "$LOG"
    set +e
    python "$HARNESS" --H "$H" --Lq 512 --Lk 1024 --out "$RESULT" --compare-cpu >>"$LOG" 2>&1
    RC=$?
    set -e
    if [ $RC -eq 0 ]; then
        # meta.cpu_reference_ok=true means torch.testing.assert_close passed.
        OK=$(python - <<PYEOF
import json
d = json.load(open("$RESULT"))
print("pass" if d.get("meta", {}).get("cpu_reference_ok") else "fail")
PYEOF
)
        echo "H=$H correctness: $OK" | tee -a "$LOG"
    else
        echo "H=$H correctness: fail (harness rc=$RC — see $LOG)" | tee -a "$LOG"
    fi
done
echo "=== [$(date -Is)] H correctness complete ==="
