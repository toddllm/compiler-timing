#!/usr/bin/env bash
# Create an isolated torch-spyre checkout at a specific SHA, ready to run
# the sentinel harnesses.
#
# Usage:
#   setup_isolated_checkout.sh <sha> <dest-dir>
#
# What it does on the pod:
#   1. Clone torch-spyre if <dest-dir> is empty.
#   2. Fetch and check out <sha>.
#   3. Symlink _C.so from the pr3806 tree (assumes torch-spyre C-extension
#      ABI hasn't changed; if it has, error and require pip install -e .).
#   4. Verify that timing_shim.py can wrap compile_fx and the pipeline
#      classes without error.
#
# Prints the absolute path of the isolated checkout on stdout.
#
# Prerequisite: the pod must have $HOME/pr3806/torch-spyre/.venv activated
# (or its path in PATH) — the venv provides torch, spyre-comms, deeptools,
# etc.

set -euo pipefail

SHA="${1:-}"
DEST="${2:-}"
if [ -z "$SHA" ] || [ -z "$DEST" ]; then
    echo "usage: setup_isolated_checkout.sh <sha> <dest-dir>" >&2
    exit 2
fi

BASE_VENV="${BASE_VENV:-$HOME/pr3806/torch-spyre/.venv}"
BASE_TREE="${BASE_TREE:-$HOME/pr3806/torch-spyre}"

if [ ! -f "$BASE_TREE/torch_spyre/_C.so" ]; then
    echo "FATAL: base _C.so not found at $BASE_TREE/torch_spyre/_C.so" >&2
    exit 3
fi

if [ ! -d "$DEST" ]; then
    mkdir -p "$(dirname "$DEST")"
    git clone --quiet https://github.com/torch-spyre/torch-spyre.git "$DEST"
fi

cd "$DEST"
# Fetch just the SHA if needed. If the SHA isn't reachable from any local
# branch, fetch the whole main plus all PR heads (PR head SHAs are only
# reachable through pull/<n>/head refs, not through main).
if ! git rev-parse --verify "$SHA^{commit}" >/dev/null 2>&1; then
    git fetch --quiet origin
fi
if ! git rev-parse --verify "$SHA^{commit}" >/dev/null 2>&1; then
    # SHA likely a PR head; fetch all PR heads.
    git fetch --quiet origin '+refs/pull/*/head:refs/remotes/origin/pr/*' 2>&1 | tail
fi
git -c advice.detachedHead=false checkout "$SHA" 2>/dev/null || {
    echo "FATAL: unable to checkout $SHA" >&2
    exit 4
}
git reset --hard "$SHA" >/dev/null

# Symlink _C.so from the shared build.
mkdir -p "$DEST/torch_spyre"
if [ ! -e "$DEST/torch_spyre/_C.so" ]; then
    ln -sf "$BASE_TREE/torch_spyre/_C.so" "$DEST/torch_spyre/_C.so"
fi

# Smoke: import torch_spyre from the isolated checkout via PYTHONPATH.
# shellcheck disable=SC1090
source "$BASE_VENV/bin/activate"
PYTHONPATH="$DEST" python - <<PYEOF
import torch, torch_spyre
assert torch_spyre.__file__.startswith("$DEST/"), (
    f"torch_spyre resolved to unexpected path: {torch_spyre.__file__}"
)
PYEOF

echo "$DEST"
