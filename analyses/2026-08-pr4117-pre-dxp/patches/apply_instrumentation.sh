#!/usr/bin/env bash
# Install the pre-DXP instrumentation into an editable torch-spyre checkout.
#
# Usage:
#   TORCH_SPYRE_REPO=/path/to/torch-spyre bash apply_instrumentation.sh
#
# Idempotent: refuses to apply if the sentinel line already exists.

set -euo pipefail

: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO to the torch-spyre repo root}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${TORCH_SPYRE_REPO}/torch_spyre/_inductor"

if [[ ! -d "${TARGET_DIR}" ]]; then
    echo "FATAL: ${TARGET_DIR} does not exist" >&2
    exit 2
fi

# 1. Vendor recorder + extra_timers into the torch-spyre tree.
cp -v "${HERE}/timing_recorder.py" "${TARGET_DIR}/timing_recorder.py"
cp -v "${HERE}/extra_timers.py"    "${TARGET_DIR}/extra_timers.py"

# 2. Apply the instrumentation patch.
if grep -q "from . import timing_recorder as _tr" \
        "${TARGET_DIR}/passes.py" 2>/dev/null; then
    echo "instrumentation appears to already be applied — skipping patch"
    exit 0
fi

cd "${TORCH_SPYRE_REPO}"
patch -p1 <"${HERE}/instrumentation.patch"

echo
echo "instrumentation applied. To revert:"
echo "    cd ${TORCH_SPYRE_REPO} && patch -R -p1 <${HERE}/instrumentation.patch"
echo "    rm ${TARGET_DIR}/timing_recorder.py ${TARGET_DIR}/extra_timers.py"
