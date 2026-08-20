#!/usr/bin/env bash
# Per-touched-file blob-equality alignment check.
#
# Given a PR number and a pod tree, verify that every file the PR
# modifies has an identical blob at the PR's base SHA and at the pod's
# copy. This is the Tier 2 alignment gate check that
# `references/measurement-policy.md` requires before an in-place
# patch-swap A/B is scientifically valid.
#
# Usage:
#   check_alignment.sh <repo> <pr_number> <pod_tree_path>
#
# Example:
#   check_alignment.sh torch-spyre/torch-spyre 3868 /home/tdeshane/pr3806/torch-spyre
#
# Exit codes:
#   0 — all touched files match byte-for-byte between pod tree and PR base
#   1 — at least one file diverges (Tier 2 fails, must escalate to Tier 3)
#   2 — usage error
#   3 — pod tree missing a file the PR touches (Tier 3 required for a
#       different reason)
#
# On divergence, prints one line per touched file:
#   OK   <path>        blob md5s match
#   DIFF <path>        blob md5s differ (with both md5s)
#   MISS <path>        file exists at PR base but not in pod tree

set -euo pipefail

REPO="${1:-}"
PR="${2:-}"
POD_TREE="${3:-}"

if [ -z "$REPO" ] || [ -z "$PR" ] || [ -z "$POD_TREE" ]; then
    echo "usage: check_alignment.sh <repo> <pr_number> <pod_tree_path>" >&2
    exit 2
fi

if [ ! -d "$POD_TREE" ]; then
    echo "FATAL: pod tree not found: $POD_TREE" >&2
    exit 2
fi

# Which SHAs?
BASE_SHA=$(gh pr view --repo "$REPO" "$PR" --json baseRefOid -q .baseRefOid)
HEAD_SHA=$(gh pr view --repo "$REPO" "$PR" --json headRefOid -q .headRefOid)
if [ -z "$BASE_SHA" ] || [ -z "$HEAD_SHA" ]; then
    echo "FATAL: could not resolve base/head SHAs from gh for $REPO#$PR" >&2
    exit 2
fi

echo "# Alignment check for $REPO PR#$PR"
echo "# base_sha:      $BASE_SHA"
echo "# head_sha:      $HEAD_SHA"
echo "# pod_tree:      $POD_TREE"

TOUCHED_FILES=$(gh pr diff --repo "$REPO" "$PR" --name-only)
if [ -z "$TOUCHED_FILES" ]; then
    echo "no files touched by PR — nothing to check"
    exit 0
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

FAILURES=0
MISSING=0
TOTAL=0

while IFS= read -r rel; do
    [ -z "$rel" ] && continue
    TOTAL=$((TOTAL + 1))
    POD_COPY="$POD_TREE/$rel"

    # Fetch the base blob from GitHub.
    if ! gh api "repos/$REPO/contents/$rel?ref=$BASE_SHA" -q .content 2>/dev/null | base64 -d > "$TMPDIR/base_blob" 2>/dev/null; then
        # File may be added by the PR — didn't exist at base.
        # Only flag as MISS if the pod-tree also lacks it.
        if [ ! -e "$POD_COPY" ]; then
            echo "OK   $rel  (added by PR, absent at pod as expected)"
        else
            echo "DIFF $rel  (added by PR, but pod has a copy — Tier 3 required)"
            FAILURES=$((FAILURES + 1))
        fi
        continue
    fi

    if [ ! -e "$POD_COPY" ]; then
        echo "MISS $rel  (file exists at PR base but not in pod tree)"
        MISSING=$((MISSING + 1))
        continue
    fi

    BASE_MD5=$(md5sum "$TMPDIR/base_blob" | awk '{print $1}')
    POD_MD5=$(md5sum "$POD_COPY"        | awk '{print $1}')

    if [ "$BASE_MD5" = "$POD_MD5" ]; then
        echo "OK   $rel  ($BASE_MD5)"
    else
        echo "DIFF $rel  base=$BASE_MD5 pod=$POD_MD5"
        FAILURES=$((FAILURES + 1))
    fi
done <<< "$TOUCHED_FILES"

echo
echo "# summary: $TOTAL touched, $FAILURES diverged, $MISSING missing at pod"

if [ "$FAILURES" -gt 0 ]; then
    echo "# TIER 2 FAILS — escalate to Tier 3 (isolated checkout at exact SHAs)"
    exit 1
elif [ "$MISSING" -gt 0 ]; then
    echo "# TIER 3 REQUIRED — pod tree does not contain every PR-touched file"
    exit 3
else
    echo "# TIER 2 PASSES — in-place patch swap on pod tree is scientifically valid"
    exit 0
fi
