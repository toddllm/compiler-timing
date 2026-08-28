#!/bin/bash
# Branch preparation for the upstream torch-spyre PR.
#
# Run this on a machine with a torch-spyre fork remote configured.
# It does NOT push. It does NOT open a PR. It only sets up the
# working tree with the exact commit(s) we want to land, so a
# human can review the diff and push when ready.
#
# Prereqs:
#   - torch-spyre repo cloned locally
#   - remote 'upstream' pointing at github.com/torch-spyre/torch-spyre
#   - remote for your fork configured (e.g. github.com/toddllm/torch-spyre)
#
# Adjust CHECKOUT_DIR, UPSTREAM_MAIN_SHA and FORK_REMOTE below.

set -euo pipefail

CHECKOUT_DIR="${TORCH_SPYRE_CHECKOUT:-$HOME/torch-spyre}"
BRANCH_NAME="${BRANCH_NAME:-tdeshane/dedup-reverse-consumer-index}"
UPSTREAM_MAIN_SHA="${UPSTREAM_MAIN_SHA:-813a2980dbd9d2e84f5006b9cde2f305e679fc71}"
FORK_REMOTE="${FORK_REMOTE:-tdeshane}"
UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"

# Compiler-timing repo path -- the files we copy into the branch
# live here.
COMPILER_TIMING_DIR="${COMPILER_TIMING_DIR:-$HOME/toddllm/compiler-timing}"
STUDY_DIR="$COMPILER_TIMING_DIR/analyses/2026-08-pr3806-frontend-timing"

cd "$CHECKOUT_DIR"

echo "=== fetching upstream ==="
git fetch "$UPSTREAM_REMOTE" main

echo "=== creating branch at $UPSTREAM_MAIN_SHA ==="
if git show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
    echo "branch already exists — refusing to overwrite. Delete it if you meant to restart."
    exit 1
fi
git checkout -b "$BRANCH_NAME" "$UPSTREAM_MAIN_SHA"

echo "=== copying production dedup_constants.py ==="
cp "$STUDY_DIR/upstream-prep/dedup_constants.py" torch_spyre/_inductor/dedup_constants.py

echo "=== copying tests ==="
cp "$STUDY_DIR/patches/test_dedup_constants_more.py" tests/inductor/test_dedup_constants_more.py

# Register the new test file with the harness's test-config system.
# The existing test_dedup_constants_config.yaml is the template.
cat > tests/configs/torch_spyre_tests/inductor/test_dedup_constants_more_config.yaml <<'YAML'
test_suite_config:
  labels: [unit, regression, integration, trunk]
  files:
    - path: ${TORCH_DEVICE_ROOT}/tests/inductor/test_dedup_constants_more.py
      unlisted_test_mode: mandatory_success
YAML

echo "=== showing what changed ==="
git status
git --no-pager diff --stat

echo
echo "=== staging + committing ==="
git add torch_spyre/_inductor/dedup_constants.py \
        tests/inductor/test_dedup_constants_more.py \
        tests/configs/torch_spyre_tests/inductor/test_dedup_constants_more_config.yaml

git commit -s -F "$STUDY_DIR/upstream-prep/commit-message.txt"

echo
echo "=== branch is ready ==="
git log --oneline -3
echo
echo "Review the commit and, when ready, push to your fork:"
echo "   git push $FORK_REMOTE $BRANCH_NAME"
echo
echo "Then open a PR via 'gh pr create' or the GitHub UI using:"
echo "   title: \$(cat $STUDY_DIR/upstream-prep/PR-title.txt)"
echo "   body:  \$STUDY_DIR/upstream-prep/PR-body.md"
