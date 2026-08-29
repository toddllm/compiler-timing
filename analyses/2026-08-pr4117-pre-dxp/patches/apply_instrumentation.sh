#!/usr/bin/env bash
# Install the pre-DXP instrumentation into an editable torch-spyre checkout,
# refusing to run if the source has drifted from the frozen baseline SHA.
#
# Usage:
#   TORCH_SPYRE_REPO=/path/to/torch-spyre bash apply_instrumentation.sh
#
# Frozen baseline is asserted three ways:
#   1. HEAD SHA equals FROZEN_SHA.
#   2. Working tree is clean (git status -s empty).
#   3. `git apply --check` accepts the patch with no offsets.
# Any check that fails aborts the script with a non-zero exit code
# before any file on the pod is touched.

set -euo pipefail

# ---- FROZEN BASELINE -------------------------------------------------------
FROZEN_SHA="3358f39e91e2a34e855d488b1b9fce3c2f0d4c2f"
# PR #4113 (dedup constant consumer index) must be an ancestor of the frozen
# baseline. The applier does not re-verify this at runtime — the study's
# summary.md records the ancestry check that was done at authoring time.
PR_4113_MERGE="c073d69cceaac91d34b01dea6545048d0d645c2c"

# ---- Repo location --------------------------------------------------------
: "${TORCH_SPYRE_REPO:?set TORCH_SPYRE_REPO to the torch-spyre repo root}"
if [[ ! -d "${TORCH_SPYRE_REPO}/.git" ]]; then
    echo "FATAL: TORCH_SPYRE_REPO='${TORCH_SPYRE_REPO}' is not a git repo" >&2
    exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${TORCH_SPYRE_REPO}/torch_spyre/_inductor"
PATCH="${HERE}/instrumentation.patch"

if [[ ! -d "${TARGET_DIR}" ]]; then
    echo "FATAL: ${TARGET_DIR} does not exist" >&2
    exit 2
fi

cd "${TORCH_SPYRE_REPO}"

# ---- 1. Exact SHA required ------------------------------------------------
HEAD_SHA="$(git rev-parse HEAD)"
if [[ "${HEAD_SHA}" != "${FROZEN_SHA}" ]]; then
    echo "FATAL: TORCH_SPYRE_REPO is at ${HEAD_SHA}" >&2
    echo "       instrumentation was authored against ${FROZEN_SHA}" >&2
    echo "       run:  git -C '${TORCH_SPYRE_REPO}' checkout ${FROZEN_SHA}" >&2
    echo "       (PR #4113 merge ${PR_4113_MERGE} must remain an ancestor)" >&2
    exit 3
fi

# ---- 2. Clean working tree ------------------------------------------------
if [[ -n "$(git status --porcelain)" ]]; then
    echo "FATAL: working tree not clean at ${HEAD_SHA}" >&2
    git status --short >&2
    exit 4
fi

# ---- 3. Sentinel: already applied? ----------------------------------------
if grep -q "from . import timing_recorder as _tr" \
        "${TARGET_DIR}/passes.py" 2>/dev/null; then
    echo "instrumentation appears already applied at ${HEAD_SHA} — nothing to do"
    exit 0
fi

# ---- 4. git apply --check (strict; no offsets, no fuzz) -------------------
if ! git apply --check "${PATCH}" 2>&1; then
    echo "FATAL: git apply --check refused the patch" >&2
    echo "       source has drifted from the frozen baseline in a way that" >&2
    echo "       even fuzzy matching cannot recover from" >&2
    exit 5
fi

# ---- 5. Vendor recorder + extra_timers ------------------------------------
cp -v "${HERE}/timing_recorder.py" "${TARGET_DIR}/timing_recorder.py"
cp -v "${HERE}/extra_timers.py"    "${TARGET_DIR}/extra_timers.py"

# ---- 6. Apply the patch (git apply, no offset/fuzz) -----------------------
git apply "${PATCH}"

echo
echo "instrumentation applied cleanly at ${HEAD_SHA}"
echo "to revert:"
echo "    cd ${TORCH_SPYRE_REPO} && git apply -R ${PATCH}"
echo "    rm ${TARGET_DIR}/timing_recorder.py ${TARGET_DIR}/extra_timers.py"
