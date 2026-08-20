#!/bin/bash
# Resolve a target (PR number, PR URL, commit range, or branch) into a
# canonical JSON record. Uses `gh` for PRs and `git` for local refs.
#
# Output is a single JSON object on stdout with:
#   kind, repo, pr_number|commit_range|branch, base_ref, head_ref,
#   base_sha, head_sha, url, changed_files.
#
# Usage:
#   resolve_target.sh 3890
#   resolve_target.sh https://github.com/torch-spyre/torch-spyre/pull/3890
#   resolve_target.sh main..my-branch
#   resolve_target.sh --local

set -euo pipefail

REPO_DEFAULT="torch-spyre/torch-spyre"

usage() {
    cat >&2 <<EOF
usage: resolve_target.sh <pr-number|pr-url|commit-range|--local>

  <pr-number>        e.g. 3890  (repo defaults to $REPO_DEFAULT)
  <pr-url>           e.g. https://github.com/OWNER/REPO/pull/NNN
  <commit-range>     e.g. main..my-branch (uses local git)
  --local            current branch vs its merge-base with origin/main
EOF
    exit 2
}

[[ $# -eq 1 ]] || usage

TARGET="$1"

emit_pr() {
    local repo="$1" pr="$2"
    local metadata
    metadata=$(GH_HOST=github.com gh pr view "$pr" --repo "$repo" \
        --json baseRefName,baseRefOid,headRefName,headRefOid,url,title,files 2>/dev/null)
    local base_ref base_sha head_ref head_sha url files
    base_ref=$(echo "$metadata" | jq -r .baseRefName)
    base_sha=$(echo "$metadata" | jq -r .baseRefOid)
    head_ref=$(echo "$metadata" | jq -r .headRefName)
    head_sha=$(echo "$metadata" | jq -r .headRefOid)
    url=$(echo "$metadata" | jq -r .url)
    files=$(echo "$metadata" | jq -c '[.files[].path]')
    jq -nc \
        --arg kind "pr" \
        --arg repo "$repo" \
        --argjson pr "$pr" \
        --arg base_ref "$base_ref" \
        --arg base_sha "$base_sha" \
        --arg head_ref "$head_ref" \
        --arg head_sha "$head_sha" \
        --arg url "$url" \
        --argjson files "$files" \
        '{kind:$kind, repo:$repo, pr_number:$pr, base_ref:$base_ref, base_sha:$base_sha,
          head_ref:$head_ref, head_sha:$head_sha, url:$url, changed_files:$files}'
}

if [[ "$TARGET" == --local ]]; then
    branch=$(git rev-parse --abbrev-ref HEAD)
    base=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)
    head=$(git rev-parse HEAD)
    files=$(git diff --name-only "$base" "$head" | jq -Rsc 'split("\n")|map(select(length>0))')
    jq -nc \
        --arg kind "branch" \
        --arg branch "$branch" \
        --arg base_sha "$base" \
        --arg head_sha "$head" \
        --argjson files "$files" \
        '{kind:$kind, branch:$branch, base_sha:$base_sha, head_sha:$head_sha, changed_files:$files}'
elif [[ "$TARGET" =~ ^[0-9]+$ ]]; then
    emit_pr "$REPO_DEFAULT" "$TARGET"
elif [[ "$TARGET" =~ ^https?://github\.com/([^/]+)/([^/]+)/pull/([0-9]+) ]]; then
    emit_pr "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}"
elif [[ "$TARGET" == *..* ]]; then
    base_ref="${TARGET%..*}"
    head_ref="${TARGET#*..}"
    base_sha=$(git rev-parse "$base_ref")
    head_sha=$(git rev-parse "$head_ref")
    files=$(git diff --name-only "$base_sha" "$head_sha" | jq -Rsc 'split("\n")|map(select(length>0))')
    jq -nc \
        --arg kind "commit_range" \
        --arg range "$TARGET" \
        --arg base_ref "$base_ref" \
        --arg base_sha "$base_sha" \
        --arg head_ref "$head_ref" \
        --arg head_sha "$head_sha" \
        --argjson files "$files" \
        '{kind:$kind, commit_range:$range, base_ref:$base_ref, base_sha:$base_sha,
          head_ref:$head_ref, head_sha:$head_sha, changed_files:$files}'
else
    usage
fi
